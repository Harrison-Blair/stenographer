# SPDX-License-Identifier: GPL-3.0-or-later
"""Live streaming driver: type committed words while recording continues.

``LiveStreamer`` runs one streamed utterance on the session-processor thread.
The recorder's PortAudio callback posts cheap partial signals; each partial
triggers a re-decode of the current audio window via the worker, the
LocalAgreement committer confirms a stable word prefix, and only the newly
confirmed delta is formatted and typed. Typed text is never revised — every
intermediate state is a prefix of the final transcript — so cancel simply
stops typing and leaves what is at the cursor.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from stenographer.asr.worker import CancelledError

if TYPE_CHECKING:
    from stenographer.asr.streaming import StreamingTranscriber
    from stenographer.asr.worker import Worker
    from stenographer.audio.capture import Recorder
    from stenographer.capabilities import Capabilities
    from stenographer.config import Config
    from stenographer.output.clipboard import ClipboardManager
    from stenographer.output.formatter import HeuristicFormatter
    from stenographer.output.inject import Injector

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


class LiveStreamer:
    """Drives one streamed utterance: partials -> commit -> format -> type."""

    def __init__(
        self,
        *,
        cfg: Config,
        recorder: Recorder,
        worker: Worker,
        injector: Injector,
        transcriber: StreamingTranscriber,
        formatter: HeuristicFormatter,
        clipboard: ClipboardManager,
        caps: Capabilities,
        abort: threading.Event,
    ) -> None:
        self._cfg = cfg
        self._recorder = recorder
        self._worker = worker
        self._injector = injector
        self._transcriber = transcriber
        self._formatter = formatter
        self._clipboard = clipboard
        self._caps = caps
        self._abort = abort
        self._signals: queue.Queue[tuple[str, np.ndarray | None]] = queue.Queue()
        # Seconds of audio trimmed off the start of the decode window.
        self._trim_offset = 0.0
        self._typed = ""
        self._max_chars_hit = False

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

    def run(self) -> str:
        """Consume signals until the utterance ends; return the typed text."""
        try:
            return self._run()
        finally:
            self._transcriber.reset()
            self._formatter.reset()

    def _run(self) -> str:
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
                log.info("live: aborted; leaving %d typed chars in place", len(self._typed))
                return self._typed
            if kind == _FINAL:
                assert samples is not None
                return self._finish(samples)
            if not self._step():
                return self._typed

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
        delta = self._transcriber.insert(words)
        if delta:
            self._emit(self._formatter.feed(delta))
            self._maybe_trim(window_seconds)
        return True

    def _finish(self, samples: np.ndarray) -> str:
        """Final decode on recording stop: flush the tail and finish output."""
        start = round(self._trim_offset * self._cfg.audio.sample_rate)
        window = samples[start:]
        # No tail-silence guard here: the user ended the utterance, decode all
        # remaining audio with the full configured beam.
        words, ok = self._decode(window, beam_size=self._cfg.asr.beam_size)
        if not ok:
            return self._typed
        delta = self._transcriber.insert(words)
        delta.extend(self._transcriber.flush())
        self._emit(self._formatter.feed(delta) + self._formatter.finalize())
        if self._typed and self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            try:
                self._clipboard.copy(self._typed)
            except Exception as exc:
                log.error("live: clipboard.copy raised: %s", exc)
        return self._typed

    # -- internal --------------------------------------------------------------

    def _interim_beam_size(self) -> int:
        beam = self._cfg.streaming.beam_size
        return self._cfg.asr.beam_size if beam is None else beam

    def _decode(self, window: np.ndarray, *, beam_size: int) -> tuple[list, bool]:
        """Run one re-decode on the worker; returns ``(words, ok)``."""
        t0 = time.monotonic()
        future = self._worker.submit_words(window, beam_size=beam_size, cancel_event=self._abort)
        try:
            words = future.result()
        except CancelledError:
            log.info("live: re-decode cancelled")
            return [], False
        except Exception as exc:
            # One failed re-decode is not fatal; the next partial (or the
            # final flush) re-decodes the same audio.
            log.error("live: re-decode failed: %s", exc)
            return [], True
        elapsed = time.monotonic() - t0
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        if window_seconds > 0:
            log.debug(
                "live: decoded %.1fs window in %.2fs (rtf=%.2f)",
                window_seconds,
                elapsed,
                elapsed / window_seconds,
            )
        return words, True

    def _emit(self, text: str) -> None:
        if not text:
            return
        max_chars = self._cfg.output.max_chars
        if len(self._typed) + len(text) > max_chars:
            # Stop typing rather than truncate a delta mid-word. Committed
            # text stays; the utterance is simply cut short.
            if not self._max_chars_hit:
                self._max_chars_hit = True
                log.warning("live: output reached output.max_chars=%d; typing stopped", max_chars)
            return
        typed = False
        try:
            typed = bool(self._injector.type_text(text, raw=True))
        except Exception as exc:
            log.error("live: injector.type_text raised: %s", exc)
        if typed:
            self._typed += text

    def _maybe_trim(self, window_seconds: float) -> None:
        """Trim the decode window at a safe committed boundary.

        Preferred trim point: the last committed word when it ends a sentence
        (that text is typed and immutable). Forced at max_buffer_seconds so
        re-decode cost stays bounded. The transcriber is rebased so later
        commits keep absolute utterance time (pause-based paragraph breaks
        that straddle a trim stay correct).
        """
        committed = self._transcriber.committed_words
        if not committed:
            return
        last = committed[-1]
        over_budget = window_seconds > self._cfg.streaming.max_buffer_seconds
        if not (last.word.rstrip().endswith(tuple(_SENTENCE_TERMINALS)) or over_budget):
            return
        dropped = last.end - self._trim_offset
        if dropped < _MIN_TRIM_SECONDS:
            return
        self._transcriber.rebase(dropped)
        self._trim_offset = last.end
        log.debug("live: trimmed %.1fs off decode window (offset=%.1fs)", dropped, last.end)


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
