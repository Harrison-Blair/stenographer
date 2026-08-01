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
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

from stenographer.asr.model import PathologicalOutputError
from stenographer.asr.worker import ASRProcessError, ASRTimeoutError, CancelledError
from stenographer.output.formatter import HeuristicFormatter

if TYPE_CHECKING:
    from stenographer.asr.model import WordInfo
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

# A re-decode is skipped when the guarded window's end moved less than this
# since the last successful decode. The audio buffer is append-only, so
# (trim offset, guarded length) identifies the decoded slice; the tail cut's
# 50 ms steps are end-aligned to the growing buffer, so the cut point can
# jitter by up to one step between snapshots even during a pure pause --
# hence a tolerance, not equality.
_REDECODE_TOLERANCE_SECONDS = 0.1

# Audio kept beyond the last non-silent window by the tail-silence guard, so
# a word's decaying tail is never cut off.
_TAIL_CUSHION_SECONDS = 0.25

# The tail-silence guard's cutoff is this many times the window's own
# 10th-percentile step RMS, so it auto-scales to the mic's noise floor
# instead of a fixed absolute threshold.
_NOISE_FLOOR_MULTIPLIER = 3

# Tail silence at least this long permits trimming at the last committed word
# even without a sentence terminal, so a thinking pause bounds the final
# decode window. Matches the model's hallucination_silence_threshold: pauses
# this long are also where Whisper starts hallucinating.
_PAUSE_TRIM_SECONDS = 2.0

_SENTENCE_TERMINALS = ".?!"

# Flushed (never-agreed) trailing words below this probability are dropped at
# finalization. Probability-based rather than energy-based so legitimately
# quiet speech is not eaten.
_MIN_FLUSH_WORD_PROBABILITY = 0.3

# Whisper's stock silence hallucinations. A flushed tail that is exactly one
# of these (normalized) after a long pre-release pause is discarded: they
# decode with high confidence, so the probability gate cannot catch them.
_HALLUCINATION_PHRASES = frozenset(
    {
        "thank you",
        "thanks for watching",
        "thank you for watching",
        "thank you so much for watching",
        "subscribe",
        "see you in the next video",
        "bye",
    }
)


class IncrementalResult(str):
    """Final text plus whether ASR recovery degraded this utterance."""

    degraded: bool
    recovery_reason: str | None

    def __new__(
        cls, text: str, *, degraded: bool = False, recovery_reason: str | None = None
    ) -> IncrementalResult:
        instance = super().__new__(cls, text)
        instance.degraded = degraded
        instance.recovery_reason = recovery_reason
        return instance


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
        # (trim offset, guarded seconds) of the last successful decode; a
        # matching window is a pause and is not re-decoded.
        self._last_decode_key: tuple[float, float] | None = None
        self._interim_suppressed = False
        self._release_started: float | None = None
        self._release_deadline: float | None = None
        self._last_failure_reason: str | None = None

    @property
    def abort(self) -> threading.Event:
        return self._abort

    # -- signals (any thread; only enqueue, never block) ----------------------

    def signal_partial(self) -> None:
        """New audio is available. Fired on the PortAudio callback thread."""
        self._signals.put((_PARTIAL, None))

    def signal_final(self, samples: np.ndarray) -> None:
        """Recording stopped; *samples* is the full finalized utterance."""
        self._release_started = time.monotonic()
        self._release_deadline = (
            self._release_started + self._cfg.incremental.release_timeout_seconds
        )
        # CTranslate2 cannot interrupt generation safely. Superseding at the
        # release callback (rather than after the driver unblocks) lets the
        # worker terminate a stuck interim immediately and restart for final.
        supersede = getattr(self._worker, "supersede_interim", None)
        if supersede is not None:
            supersede()
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
            kind, samples = self._next_signal()
            if kind == _ABORT or self._abort.is_set():
                log.info("incremental: aborted")
                return None
            if kind == _FINAL:
                assert samples is not None
                return self._finish(samples)
            if not self._step():
                # Shutdown queues the finalized samples before globally
                # cancelling the worker. If that cancellation lands during an
                # interim decode, consume the already-pending final instead of
                # dropping the utterance. Never wait here: a cancellation with
                # no final belongs to an abort/failure path.
                pending = self._next_signal(block=False)
                if pending is not None:
                    pending_kind, pending_samples = pending
                    if (
                        pending_kind == _FINAL
                        and pending_samples is not None
                        and not self._abort.is_set()
                    ):
                        return self._finish(pending_samples)
                return None

    def _next_signal(self, *, block: bool = True) -> tuple[str, np.ndarray | None] | None:
        """Return the highest-priority pending signal, coalescing partials."""
        try:
            if block:
                kind, samples = self._signals.get()
            else:
                kind, samples = self._signals.get_nowait()
        except queue.Empty:
            return None
        # Re-decodes are cumulative, so pending partials collapse into the
        # newest signal; a queued final or abort wins outright.
        while True:
            try:
                next_kind, next_samples = self._signals.get_nowait()
            except queue.Empty:
                break
            # An abort always wins; a final wins over anything but an abort.
            if next_kind == _ABORT or (next_kind == _FINAL and kind != _ABORT):
                kind, samples = next_kind, next_samples
        return kind, samples

    def _step(self) -> bool:
        """One interim re-decode. Returns False when aborted mid-decode."""
        if self._interim_suppressed:
            return True
        window = self._recorder.snapshot(self._trim_offset)
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        guarded = _prepare_decode_audio(
            window,
            self._cfg.audio.sample_rate,
            self._cfg.audio.min_speech_rms,
        )
        if guarded.shape[0] == 0:
            # No speech since the trim offset also means every committed word
            # ends at or before it, so there is nothing to trim either.
            return True
        guarded_seconds = guarded.shape[0] / self._cfg.audio.sample_rate
        tail_silence = window_seconds - guarded_seconds
        if self._matches_last_decode(guarded_seconds):
            # A pause: the guarded audio is what the last decode already saw.
            # Re-decoding it would reproduce the same hypothesis, wasting the
            # worker and letting a hallucination commit via trivial agreement.
            log.info("incremental: window unchanged (%.2fs); skipping re-decode", guarded_seconds)
            self._maybe_trim(window_seconds, tail_silence)
            return True
        words, ok = self._decode(guarded, beam_size=self._interim_beam_size())
        if not ok:
            return False
        if words is not None:
            # Keyed to the pre-trim offset: a trim below invalidates the key,
            # forcing exactly one re-decode of the shortened window. A failed
            # decode leaves the key stale so the next partial retries.
            self._last_decode_key = (self._trim_offset, guarded_seconds)
            delta = self._transcriber.insert(words)
            if delta:
                self._transcript += self._formatter.feed(delta)
            self._publish_preview()
        # Trimming is gated on the budget, not on this re-decode having
        # committed anything: an agreement-free stretch commits no delta for
        # many partials in a row, and that is exactly when the window is
        # growing and max_buffer_seconds most needs to bound it.
        self._maybe_trim(window_seconds, tail_silence)
        return True

    def _finish(self, samples: np.ndarray) -> IncrementalResult | None:
        """Final-decode, flush, and return formatted output without delivery."""
        start = round(self._trim_offset * self._cfg.audio.sample_rate)
        window = samples[start:]
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        guarded = _prepare_decode_audio(
            window,
            self._cfg.audio.sample_rate,
            self._cfg.audio.min_speech_rms,
        )
        if guarded.shape[0] == 0:
            # A silent final tail must not promote the last provisional
            # hypothesis. Already committed text remains append-only.
            log.info("incremental: silent final tail; discarding provisional text")
            self._transcript += self._formatter.finalize()
            self._publish_preview(final=True)
            return self._result(self._transcript)
        guarded_seconds = guarded.shape[0] / self._cfg.audio.sample_rate
        tail_silence = window_seconds - guarded_seconds
        degraded = False
        recovery_reason: str | None = None
        if (
            self._matches_last_decode(guarded_seconds)
            and self._interim_beam_size() == self._cfg.asr.beam_size
        ):
            # The last interim decode already covered this exact audio at the
            # same beam, so the final decode would reproduce its hypothesis
            # -- flush that hypothesis directly instead of paying for it.
            log.info("incremental: final window matches last interim decode; skipping final decode")
            delta = _gate_flushed_tail(self._transcriber.flush(), tail_silence)
        else:
            words, ok = self._decode(guarded, beam_size=self._cfg.asr.beam_size, final=True)
            if not ok:
                return None
            if words is None:
                # The final decode failed but the utterance was not cancelled.
                # Flush the last interim hypothesis instead of discarding the
                # dictation: the audio since that hypothesis is lost either
                # way, but everything already committed must still reach the
                # user.
                reason = self._last_failure_reason or "process-failure"
                degraded = True
                recovery_reason = reason
                log.warning(
                    "incremental: final decode failed; recovering preview reason=%s", reason
                )
                delta = _gate_flushed_tail(self._transcriber.flush(), tail_silence)
            else:
                delta = self._transcriber.insert(words)
                delta.extend(_gate_flushed_tail(self._transcriber.flush(), tail_silence))
        self._transcript += self._formatter.feed(delta) + self._formatter.finalize()
        self._publish_preview(final=True)
        return self._result(
            self._transcript,
            degraded=degraded,
            recovery_reason=recovery_reason,
        )

    # -- internal --------------------------------------------------------------

    def _interim_beam_size(self) -> int:
        beam = self._cfg.incremental.beam_size
        return self._cfg.asr.beam_size if beam is None else beam

    def _matches_last_decode(self, guarded_seconds: float) -> bool:
        key = self._last_decode_key
        return (
            key is not None
            and key[0] == self._trim_offset
            and abs(guarded_seconds - key[1]) < _REDECODE_TOLERANCE_SECONDS
        )

    def _decode(
        self, window: np.ndarray, *, beam_size: int, final: bool = False
    ) -> tuple[list | None, bool]:
        """Run one re-decode on the worker; returns ``(words, ok)``.

        ``ok`` is False only when the utterance was cancelled. ``words`` is
        None when the decode failed but the utterance continues -- distinct
        from an empty list, which is a successful decode that found no
        speech. Callers must not feed a failed decode into the committer.

        The *final* decode is exempt from the worker's global cancel: shutdown
        fires it to abort interim re-decodes, and cancelling the final one
        would discard the whole utterance. ``self._abort`` still applies.
        """
        t0 = time.monotonic()
        deadline = (
            self._release_deadline
            if final
            else time.monotonic() + (self._cfg.incremental.interim_timeout_seconds)
        )
        future = self._worker.submit_words(
            window,
            beam_size=beam_size,
            cancel_event=self._abort,
            ignore_global_cancel=final,
            deadline=deadline,
            priority="final" if final else "interim",
        )
        try:
            words = future.result()
        except CancelledError:
            log.info("incremental: re-decode cancelled")
            return None, False
        except ASRTimeoutError:
            self._last_failure_reason = "timeout"
            if not final:
                self._interim_suppressed = True
                log.warning("incremental: interim decode timed out; suppressing further previews")
            else:
                log.warning("incremental: final decode timed out")
            return None, True
        except PathologicalOutputError:
            self._last_failure_reason = "pathological-output"
            log.warning("incremental: decoder output rejected as pathological")
            return None, True
        except ASRProcessError:
            self._last_failure_reason = "process-failure"
            log.warning("incremental: ASR child failed")
            return None, True
        except Exception as exc:
            # One failed re-decode is not fatal; the next partial (or the
            # final flush) re-decodes the same audio.
            self._last_failure_reason = "process-failure"
            log.error("incremental: re-decode failed: %s", type(exc).__name__)
            return None, True
        elapsed = time.monotonic() - t0
        window_seconds = window.shape[0] / self._cfg.audio.sample_rate
        if window_seconds > 0:
            mean_confidence = sum(word.probability for word in words) / len(words) if words else 0.0
            log.info(
                "incremental: decoded %.3fs in %.3fs (rtf=%.2f) word_count=%d mean_confidence=%.3f",
                window_seconds,
                elapsed,
                elapsed / window_seconds,
                len(words),
                mean_confidence,
            )
        return words, True

    def _result(
        self,
        text: str,
        *,
        degraded: bool = False,
        recovery_reason: str | None = None,
    ) -> IncrementalResult:
        if self._release_started is not None:
            latency = time.monotonic() - self._release_started
            log.info(
                "incremental: release result ready latency=%.3fs degraded=%s reason=%s",
                latency,
                degraded,
                recovery_reason or "none",
            )
        return IncrementalResult(
            text,
            degraded=degraded,
            recovery_reason=recovery_reason,
        )

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

    def _maybe_trim(self, window_seconds: float, tail_silence_seconds: float) -> None:
        """Trim the decode window at a safe committed boundary.

        Preferred trim point: the last committed word when it ends a sentence
        (that text is stable and immutable). Also permitted after a sustained
        tail silence -- a thinking pause has no terminal punctuation, and
        without a trim the pause would grow the final decode window. Forced
        at max_buffer_seconds so re-decode cost stays bounded. The transcriber
        is rebased so later commits keep absolute utterance time (pause-based
        paragraph breaks that straddle a trim stay correct).
        """
        committed = self._transcriber.committed_words
        if not committed:
            return
        last = committed[-1]
        over_budget = window_seconds > self._cfg.incremental.max_buffer_seconds
        pause = tail_silence_seconds >= _PAUSE_TRIM_SECONDS
        if not (last.word.rstrip().endswith(tuple(_SENTENCE_TERMINALS)) or over_budget or pause):
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

    The cutoff is relative to the window's own 10th-percentile step RMS (its
    observed noise floor), not a fixed absolute threshold, so the guard
    auto-scales to any mic. A cushion is kept past the last non-silent window.
    The separate energy gate rejects uniformly silent windows that this
    self-relative calculation cannot distinguish from uniform speech.
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


def _prepare_decode_audio(window: np.ndarray, rate: int, min_speech_rms: float) -> np.ndarray:
    """Energy-gate and tail-trim one interim or final decode window."""
    peak_rms, has_speech = _speech_energy(window, rate, min_speech_rms)
    input_seconds = window.shape[0] / rate
    if not has_speech:
        log.info(
            "incremental: energy gate rejected audio input_duration=%.3fs "
            "peak_frame_rms=%.6f threshold=%.6f",
            input_seconds,
            peak_rms,
            min_speech_rms,
        )
        return window[:0]
    trimmed = _cut_trailing_silence(window, rate)
    kept_seconds = trimmed.shape[0] / rate
    log.info(
        "incremental: audio prepared input_duration=%.3fs trimmed_duration=%.3fs "
        "tail_removed=%.3fs peak_frame_rms=%.6f",
        input_seconds,
        kept_seconds,
        input_seconds - kept_seconds,
        peak_rms,
    )
    return trimmed


def _gate_flushed_tail(words: list[WordInfo], tail_silence_seconds: float) -> list[WordInfo]:
    """Filter the never-agreed flushed tail at finalization.

    Applied only to ``flush()`` output -- words that never reached agreement
    -- never to committed words. Two stages: drop the trailing run of
    sub-threshold-probability words, then discard the whole remaining tail
    when it is exactly a stock Whisper silence hallucination and the
    utterance ended in a long pause (the hallucination-inducing condition).
    Known tradeoff: a genuine closing "thank you" followed by a long pause
    before release is eaten too; the info log makes that visible.
    """
    kept = _drop_low_confidence_tail(words)
    if kept and tail_silence_seconds >= _PAUSE_TRIM_SECONDS:
        text = _normalize_phrase("".join(word.word for word in kept))
        if text in _HALLUCINATION_PHRASES:
            log.info(
                "incremental: dropped hallucinated tail after %.1fs pause: %r",
                tail_silence_seconds,
                text,
            )
            return []
    return kept


def _drop_low_confidence_tail(words: list[WordInfo]) -> list[WordInfo]:
    """Drop the trailing run of words below the flush probability floor.

    A backward walk that stops at the first confident word, so a low-prob
    word followed by a confident one is never removed.
    """
    end = len(words)
    while end > 0 and words[end - 1].probability < _MIN_FLUSH_WORD_PROBABILITY:
        end -= 1
    if end < len(words):
        dropped = "".join(word.word for word in words[end:]).strip()
        log.info(
            "incremental: dropped %d low-confidence flushed word(s): %r",
            len(words) - end,
            dropped,
        )
    return words[:end]


def _normalize_phrase(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return " ".join(cleaned.split())


def _speech_energy(window: np.ndarray, rate: int, threshold: float) -> tuple[float, bool]:
    """Return peak 50 ms RMS and whether two adjacent frames clear *threshold*."""
    mono = window[:, 0] if window.ndim == 2 else window
    if mono.size == 0:
        return 0.0, False
    step = max(1, rate // 20)
    frame_rms = [
        float(np.sqrt(np.mean(np.square(mono[start : start + step], dtype=np.float64))))
        for start in range(0, mono.shape[0], step)
    ]
    peak = max(frame_rms, default=0.0)
    if threshold == 0:
        return peak, True
    above = [rms >= threshold for rms in frame_rms]
    return peak, any(left and right for left, right in pairwise(above))
