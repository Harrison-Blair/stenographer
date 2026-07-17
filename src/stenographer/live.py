# SPDX-License-Identifier: GPL-3.0-or-later
"""Live streaming driver: paste committed words while recording continues.

``LiveStreamer`` runs one streamed utterance on the session-processor thread.
The recorder's PortAudio callback posts cheap partial signals; each partial
triggers a re-decode of the current audio window via the worker, the
LocalAgreement committer confirms a stable word prefix, and only the newly
confirmed delta is formatted, copied to the clipboard and pasted at the
cursor. Delivered text is never revised — every intermediate state is a
prefix of the final transcript — so cancel simply stops pasting and leaves
what is at the cursor. A delta that fails to deliver latches output off for
the rest of the utterance rather than pasting a later delta past the gap.
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
    """Drives one streamed utterance: partials -> commit -> format -> paste."""

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
        # What actually reached the cursor (the prefix invariant, and run()'s
        # return value) vs. everything the user said. These answer different
        # questions and diverge exactly when delivery latches off below.
        self._typed = ""
        self._transcript = ""
        self._max_chars_hit = False
        # Latched when a delta fails to deliver: no further delta may be
        # pasted, or the delivered text would continue past a gap.
        self._delivery_failed = False

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
        if words is not None:
            delta = self._transcriber.insert(words)
            if delta:
                self._emit(self._formatter.feed(delta))
        # Trimming is gated on the budget, not on this re-decode having
        # committed anything: an agreement-free stretch commits no delta for
        # many partials in a row, and that is exactly when the window is
        # growing and max_buffer_seconds most needs to bound it.
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
        delta: list = []
        if words is None:
            # The final decode failed. Feeding an empty hypothesis to insert()
            # would overwrite the transcriber's uncommitted tail with [], so
            # the flush below would return nothing and the user's last words
            # would vanish. Skip straight to the flush: the tail is the best
            # hypothesis we still have.
            log.warning("live: final decode failed; flushing the uncommitted tail as-is")
        else:
            delta = self._transcriber.insert(words)
        delta.extend(self._transcriber.flush())
        self._emit(self._formatter.feed(delta) + self._formatter.finalize())
        # The clipboard is the independent fallback for text that did not
        # reach the cursor, so once delivery latched off it must carry the
        # full transcript rather than the delivered prefix -- otherwise the
        # undelivered remainder is neither pasted nor recoverable. On every
        # other path _typed is copied exactly as before: on the happy path it
        # already IS the full transcript, and an output.max_chars cap is a
        # deliberate limit on output that the clipboard must not quietly
        # override.
        text = self._transcript if self._delivery_failed else self._typed
        if text and self._cfg.clipboard.enabled and self._caps.has_wl_copy:
            try:
                self._clipboard.copy(text)
            except Exception as exc:
                log.error("live: clipboard.copy raised: %s", exc)
        return self._typed

    # -- internal --------------------------------------------------------------

    def _interim_beam_size(self) -> int:
        beam = self._cfg.streaming.beam_size
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
            log.info("live: re-decode cancelled")
            return None, False
        except Exception as exc:
            # One failed re-decode is not fatal; the next partial (or the
            # final flush) re-decodes the same audio.
            log.error("live: re-decode failed: %s", exc)
            return None, True
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
        # Accumulated before the latch check and independently of delivery
        # success, so it keeps growing after output has stopped -- that is
        # the whole point: it is what _finish() falls back to on the
        # clipboard so the undelivered remainder stays recoverable.
        self._transcript += text
        if self._delivery_failed or self._max_chars_hit:
            return
        max_chars = self._cfg.output.max_chars
        if len(self._typed) + len(text) > max_chars:
            # Stop typing rather than truncate a delta mid-word. Committed
            # text stays; the utterance is simply cut short.
            #
            # This latches: a later, shorter delta might fit under the cap,
            # but pasting it would continue the delivered text past the delta
            # skipped here -- a hole in the middle, no longer a prefix of the
            # transcript. Cutting the utterance short at a word boundary is
            # the documented behaviour; resuming past a gap is silently wrong.
            self._max_chars_hit = True
            log.warning("live: output reached output.max_chars=%d; typing stopped", max_chars)
            return
        delivered = False
        try:
            # Paste only on a fully successful copy. ClipboardManager.copy()
            # populates the regular clipboard AND the primary selection, and
            # returns False if either failed -- so a False here can mean the
            # two selections now disagree (clipboard holds this delta, primary
            # still holds the previous one). The chord reads whichever
            # selection the client prefers, so pasting now could deliver a
            # stale, out-of-order word.
            #
            # copy()'s strict return does not cause that desync -- a partial
            # wl-copy failure desyncs the selections whatever it returns -- it
            # is the only thing that makes the desync visible here. Loosening
            # it would drop the signal and leave the desync, breaking the
            # prefix invariant with nothing able to observe it.
            if self._clipboard.copy(text, primary=True):
                delivered = bool(self._injector.paste())
        except Exception as exc:
            log.error("live: paste delivery raised: %s", exc)
        if delivered:
            self._typed += text
            return
        # Never deliver past a gap. A later delta pasted after a dropped one
        # would leave the delivered text with a hole in it -- no longer a
        # prefix of the final transcript, and silently wrong rather than a
        # visible error. Stopping cleanly at a prefix boundary is correct;
        # guessing at a resynchronisation is not. _finish() still re-copies
        # the accumulated transcript, so the clipboard fallback survives.
        if not self._delivery_failed:
            self._delivery_failed = True
            log.warning(
                "live: delta delivery failed; output stopped at %d chars to keep "
                "delivered text a prefix of the transcript",
                len(self._typed),
            )

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
