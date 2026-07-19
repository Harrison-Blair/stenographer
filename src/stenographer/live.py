# SPDX-License-Identifier: GPL-3.0-or-later
"""Incremental transcription driver for one recorded utterance.

The recorder posts cheap partial signals. Each signal cumulatively re-decodes
the current audio window, LocalAgreement commits an append-only stable prefix,
and the newest uncommitted hypothesis is published as a revisable preview
tail. This module never writes to the clipboard or focused application.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

from stenographer.asr.worker import CancelledError
from stenographer.output.formatter import HeuristicFormatter

if TYPE_CHECKING:
    from stenographer.asr.streaming import StreamingTranscriber
    from stenographer.asr.worker import Worker
    from stenographer.audio.capture import Recorder
    from stenographer.config import Config

log = logging.getLogger(__name__)

_PARTIAL = "partial"
_FINAL = "final"
_ABORT = "abort"

# A trim must drop at least this much audio to be worth rebasing over.
_MIN_TRIM_SECONDS = 1.0

# Audio kept beyond the last non-silent window by the tail-silence guard, so
# a word's decaying tail is never cut off.
_TAIL_CUSHION_SECONDS = 0.25

# The tail-silence guard's cutoff is this many times the window's own
# 10th-percentile step RMS, so it auto-scales to the mic's noise floor
# instead of a fixed absolute threshold.
_NOISE_FLOOR_MULTIPLIER = 3

# Dead-air detector, NOT the trim gate: a window whose loudest step never
# clears this is genuinely silent throughout (no speech anywhere in it), so
# the self-relative trim below -- which cannot tell uniform-loud from
# uniform-silent -- is skipped in favor of returning empty outright. Set
# deliberately below quiet-mic speech RMS (~0.001-0.005) and above ambient
# noise floor (~0.0002) per repo memory `quiet-mic-rms.md`.
_SILENCE_FLOOR_RMS = 0.0005

_SENTENCE_TERMINALS = ".?!"


class IncrementalDriver:
    """Drive partial decodes and return one fully formatted final transcript."""

    def __init__(
        self,
        *,
        cfg: Config,
        recorder: Recorder,
        worker: Worker,
        transcriber: StreamingTranscriber,
        formatter: HeuristicFormatter,
        abort: threading.Event,
        on_preview: Callable[[str, str], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._recorder = recorder
        self._worker = worker
        self._transcriber = transcriber
        self._formatter = formatter
        self._abort = abort
        self._on_preview = on_preview
        self._signals: queue.Queue[tuple[str, np.ndarray | None]] = queue.Queue()
        # Seconds of audio trimmed off the start of the decode window.
        self._trim_offset = 0.0
        self._transcript = ""

    @property
    def abort(self) -> threading.Event:
        return self._abort

    # -- signals (any thread; only enqueue, never block) ----------------------

    def signal_partial(self) -> None:
        """New audio is available. Fired on the PortAudio callback thread."""
        self._signals.put((_PARTIAL, None))

    def signal_final(self, samples: np.ndarray) -> None:
        """Recording stopped; *samples* is the full finalized utterance."""
        self._signals.put((_FINAL, samples))

    def signal_abort(self) -> None:
        """Wake the driver promptly after the abort event was set."""
        self._signals.put((_ABORT, None))

    # -- driver (session-processor thread) ------------------------------------

    def run(self) -> str | None:
        """Return the final transcript, or ``None`` after cancellation/failure."""
        try:
            return self._run()
        finally:
            self._transcriber.reset()
            self._formatter.reset()

    def _run(self) -> str | None:
        while True:
            kind, samples = self._signals.get()
            # Coalesce: re-decodes are cumulative, so pending partials collapse
            # into the newest signal; a queued final or abort wins outright.
            while True:
                try:
                    next_kind, next_samples = self._signals.get_nowait()
                except queue.Empty:
                    break
                # An abort always wins; a final wins over anything but an
                # abort; extra partials are dropped (the next re-decode reads
                # the newest audio window anyway).
                if next_kind == _ABORT or (next_kind == _FINAL and kind != _ABORT):
                    kind, samples = next_kind, next_samples
            if kind == _ABORT or self._abort.is_set():
                log.info("incremental: aborted")
                return None
            if kind == _FINAL:
                assert samples is not None
                return self._finish(samples)
            if not self._step():
                return None

    def _step(self) -> bool:
        """One interim re-decode. Returns False when aborted mid-decode."""
        window = self._recorder.snapshot(self._trim_offset)
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        guarded = _cut_trailing_silence(window, self._cfg.audio.sample_rate)
        if guarded.shape[0] == 0:
            return True
        words, ok = self._decode(guarded, beam_size=self._interim_beam_size())
        if not ok:
            return False
        if words is not None:
            delta = self._transcriber.insert(words)
            if delta:
                self._transcript += self._formatter.feed(delta)
            self._publish_preview()
        # Trimming is gated on the budget, not on this re-decode having
        # committed anything: an agreement-free stretch commits no delta for
        # many partials in a row, and that is exactly when the window is
        # growing and max_buffer_seconds most needs to bound it.
        self._maybe_trim(window_seconds)
        return True

    def _finish(self, samples: np.ndarray) -> str | None:
        """Final-decode, flush, and return formatted output without delivery."""
        start = round(self._trim_offset * self._cfg.audio.sample_rate)
        window = samples[start:]
        # No tail-silence guard here: the user ended the utterance, decode all
        # remaining audio with the full configured beam.
        words, ok = self._decode(window, beam_size=self._cfg.asr.beam_size)
        if not ok or words is None:
            return None
        delta = self._transcriber.insert(words)
        delta.extend(self._transcriber.flush())
        self._transcript += self._formatter.feed(delta) + self._formatter.finalize()
        self._publish_preview(final=True)
        return self._transcript

    # -- internal --------------------------------------------------------------

    def _interim_beam_size(self) -> int:
        beam = self._cfg.incremental.beam_size
        return self._cfg.asr.beam_size if beam is None else beam

    def _decode(self, window: np.ndarray, *, beam_size: int) -> tuple[list | None, bool]:
        """Run one re-decode on the worker; returns ``(words, ok)``.

        ``ok`` is False only when the utterance was cancelled. ``words`` is
        None when the decode failed but the utterance continues -- distinct
        from an empty list, which is a successful decode that found no
        speech. Callers must not feed a failed decode into the committer.
        """
        t0 = time.monotonic()
        future = self._worker.submit_words(window, beam_size=beam_size, cancel_event=self._abort)
        try:
            words = future.result()
        except CancelledError:
            log.info("incremental: re-decode cancelled")
            return None, False
        except Exception as exc:
            # One failed re-decode is not fatal; the next partial (or the
            # final flush) re-decodes the same audio.
            log.error("incremental: re-decode failed: %s", exc)
            return None, True
        elapsed = time.monotonic() - t0
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        if window_seconds > 0:
            log.debug(
                "incremental: decoded %.1fs window in %.2fs (rtf=%.2f)",
                window_seconds,
                elapsed,
                elapsed / window_seconds,
            )
        return words, True

    def _publish_preview(self, *, final: bool = False) -> None:
        if self._on_preview is None:
            return
        stable = self._transcript
        if final:
            provisional = ""
        else:
            formatter = HeuristicFormatter(
                self._cfg.formatting,
                append_trailing_space=False,
            )
            all_words = self._transcriber.committed_words + self._transcriber.provisional_words
            complete = formatter.format_batch(all_words)
            stable_formatter = HeuristicFormatter(
                self._cfg.formatting,
                append_trailing_space=False,
            )
            stable = stable_formatter.format_batch(self._transcriber.committed_words)
            provisional = complete[len(stable) :]
        try:
            self._on_preview(stable, provisional)
        except Exception as exc:
            log.debug("incremental: preview consumer failed: %s", exc)

    def _maybe_trim(self, window_seconds: float) -> None:
        """Trim the decode window at a safe committed boundary.

        Preferred trim point: the last committed word when it ends a sentence
        (that text is stable and immutable). Forced at max_buffer_seconds so
        re-decode cost stays bounded. The transcriber is rebased so later
        commits keep absolute utterance time (pause-based paragraph breaks
        that straddle a trim stay correct).
        """
        committed = self._transcriber.committed_words
        if not committed:
            return
        last = committed[-1]
        over_budget = window_seconds > self._cfg.incremental.max_buffer_seconds
        if not (last.word.rstrip().endswith(tuple(_SENTENCE_TERMINALS)) or over_budget):
            return
        dropped = last.end - self._trim_offset
        if dropped < _MIN_TRIM_SECONDS:
            return
        self._transcriber.rebase(dropped)
        self._trim_offset = last.end
        log.debug("incremental: trimmed %.1fs off decode window (offset=%.1fs)", dropped, last.end)


# Compatibility for third-party imports during the streaming-to-incremental
# transition. New code should use IncrementalDriver.
LiveStreamer = IncrementalDriver


def _cut_trailing_silence(window: np.ndarray, rate: int) -> np.ndarray:
    """Drop trailing sub-noise-floor audio before an interim re-decode.

    Whisper hallucinates over trailing silence, and word-level decoding loses
    the per-segment no_speech_prob gate — this guard is its replacement. The
    cutoff is relative to the window's own 10th-percentile step RMS (its
    observed noise floor), not a fixed absolute threshold, so the guard
    auto-scales to any mic. A cushion is kept past the last non-silent
    window; the final decode (which skips this guard) covers whatever the
    guard shaved off.
    """
    mono = window[:, 0] if window.ndim == 2 else window
    step = max(1, rate // 20)  # 50 ms windows
    n_steps = mono.shape[0] // step
    if n_steps < 10:
        return window
    # End-aligned, so these are exactly the chunks the backward-walk trim
    # loop below evaluates (any leading remainder shorter than one step is
    # excluded from both).
    tail = mono[mono.shape[0] - n_steps * step :]
    step_rms = np.sqrt(np.mean(np.square(tail.reshape(n_steps, step)), axis=1))
    if np.max(step_rms) < _SILENCE_FLOOR_RMS:
        # Dead air throughout: even the loudest step never reaches speech
        # level, so there is nothing to decode.
        return window[:0]
    floor = np.percentile(step_rms, 10)
    cutoff = floor * _NOISE_FLOOR_MULTIPLIER
    end = mono.shape[0]
    while end >= step:
        rms = float(np.sqrt(np.mean(np.square(mono[end - step : end]))))
        # Strict >: a step exactly at cutoff (e.g. both 0 for a window with a
        # true-digital-silence tail, where the 10th-percentile floor is
        # itself exactly 0) must not count as "above" it.
        if rms > cutoff:
            break
        end -= step
    else:
        # No step ever reached cutoff: the window has no internal RMS
        # variance to distinguish a quiet tail from the rest (e.g. uniformly
        # loud speech, or uniform silence) -- a self-relative cutoff cannot
        # tell those apart, so there is nothing safe to trim.
        return window
    end = min(mono.shape[0], end + round(_TAIL_CUSHION_SECONDS * rate))
    return window[:end]
