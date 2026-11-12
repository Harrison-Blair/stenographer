# SPDX-License-Identifier: GPL-3.0-or-later
"""The speech check → decode → format core shared by the daemon and ``transcribe``.

One utterance produces exactly one INFO summary line, whether it came from the
hotkey or from ``stenographer transcribe <file>``. Both paths fill the same
:class:`UtteranceRecord` as their phases complete and hand it to
:func:`log_summary`, so a file run is directly comparable with a live one; both
also downmix through :func:`downmix` and format through :func:`transcript_text`,
so neither can drift from the other's audio or spacing.

The record is filled in from several threads (hotkey, pipeline) but only ever
for the one utterance in flight, which the daemon's state lock serialises.
:func:`summary_fields`, :func:`downmix` and :func:`transcript_text` are pure;
the two ``log_*`` helpers exist so the ``fmt_event`` call sites stay literal."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.logging.pipeline import fmt_event
from stenographer.lib.transcribe.format import format_transcript
from stenographer.lib.transcribe.text import count_words

if TYPE_CHECKING:
    import numpy as np

    from stenographer.lib.audio.records import CaptureStats
    from stenographer.lib.delivery.timings import DeliveryTimings
    from stenographer.lib.refine.results import RefineResult
    from stenographer.lib.transcribe.results import TranscriptionResult, WorkerTimings

from stenographer.lib.transcribe.utterance_record import UtteranceRecord

log = logging.getLogger(__name__)

_LEVEL_FRAME_SECONDS = 0.050


def apply_capture(record: UtteranceRecord | None, stats: CaptureStats | None) -> None:
    """Project secured recorder measurements without sampling a clock. PURE."""
    if record is None or stats is None:
        return
    record.activate_ms = stats.activate_ms
    if stats.first_callback_at is not None:
        record.press_to_callback_ms = (stats.first_callback_at - record.started_at) * 1000
    record.activation_to_callback_ms = stats.activation_to_callback_ms
    record.capture_s = stats.input_frames / stats.input_rate
    record.device_name = stats.device_name
    record.input_rate = stats.input_rate
    record.channels = stats.channels
    record.finalize_ms = stats.finalize_ms
    record.callback_count = stats.callback_count
    record.in_frames = stats.input_frames
    record.out_frames = stats.output_frames
    record.capped = stats.capped


def apply_levels(record: UtteranceRecord | None, samples: np.ndarray) -> None:
    """Project the capture level and clipping, measured on 50 ms frames. PURE."""
    if record is None:
        return
    import numpy as np

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = round(SAMPLE_RATE * _LEVEL_FRAME_SECONDS)
    n_frames = audio.size // frame
    if n_frames:
        trimmed = audio[: n_frames * frame].reshape(n_frames, frame)
        rms = np.empty(n_frames, dtype=np.float32)
        for start in range(0, n_frames, 100):
            chunk = trimmed[start : start + 100]
            rms[start : start + len(chunk)] = np.sqrt(np.mean(chunk * chunk, axis=1))
        record.peak_rms = float(rms.max())
        record.mean_rms = float(rms.mean())
    else:
        record.peak_rms = 0.0
        record.mean_rms = 0.0
    clipped = sum(
        np.count_nonzero(np.abs(block) >= 0.999)
        for block in np.nditer(
            samples, flags=["external_loop", "buffered", "zerosize_ok"], buffersize=65_536
        )
    )
    record.clipping_fraction = float(clipped / samples.size) if samples.size else 0.0


def apply_recognition(record: UtteranceRecord | None, result: TranscriptionResult) -> None:
    """Keep accepted recognition even when a subsequent phase fails. PURE."""
    if record is None:
        return
    record.segments = len(result.segments)
    record.words = sum(len(segment.words) for segment in result.segments)
    record.chars_raw = len(result.text)
    record.recognized_words = count_words(result.text)
    record.asr_audio_s = record.capture_s


def apply_speech(record: UtteranceRecord | None, speech_seconds: float) -> None:
    """Record the speech duration that the VAD found in the capture. PURE."""
    if record is None:
        return
    record.vad_frames = round(speech_seconds * SAMPLE_RATE)
    record.vad_s = speech_seconds


def apply_formatting(
    record: UtteranceRecord | None, text: str, *, started_at: float, ready_at: float
) -> None:
    """Record successful formatting, including empty output, before delivery. PURE."""
    if record is None:
        return
    record.chars_out = len(text)
    record.final_words = count_words(text)
    record.format_ms = (ready_at - started_at) * 1000
    if record.stopped_at is not None:
        record.stop_to_ready_ms = (ready_at - record.stopped_at) * 1000


def apply_refinement(
    record: UtteranceRecord | None,
    result: RefineResult | None,
    *,
    delivered: str | None = None,
) -> None:
    """Project one refine verdict, and the text it produced, as numbers. PURE.

    *delivered* is the string that will actually reach the clipboard, given
    only when the refined form replaced the formatted one: ``chars_out`` and
    ``final_words`` describe what the user gets, and every later word count
    (``copied_words``, ``chord_words``) reads them. Readiness timing is *not*
    restated — ``stop_to_ready_ms`` and ``format_ms`` keep measuring the local
    formatter, and ``refine_ms`` accounts for the model separately.
    """
    if record is None:
        return
    if result is not None:
        record.refine_attempted = result.attempted
        record.refine_applied = result.applied
        record.refine_failed = result.failed
        record.refine_chars_in = result.chars_in
        record.refine_chars_out = result.chars_out
        record.refine_ms = result.duration_ms
    if delivered is not None:
        record.chars_out = len(delivered)
        record.final_words = count_words(delivered)


def apply_worker_timings(record: UtteranceRecord | None, timings: WorkerTimings | None) -> None:
    """Absent phase measurements remain unknown; warm-up load timing survives. PURE."""
    if record is None or timings is None:
        return
    record.lock_wait_ms = timings.lock_wait_ms
    if timings.load_ms is not None:
        record.load_ms = timings.load_ms
    record.decode_ms = timings.decode_ms
    record.round_trip_ms = timings.round_trip_ms


def apply_delivery(
    record: UtteranceRecord | None,
    timings: DeliveryTimings | None,
    *,
    attempted: bool,
    observed_at: float,
) -> None:
    """Project confirmed delivery boundaries without changing readiness. PURE."""
    if record is None or not attempted or timings is None:
        return
    record.copy_ms = timings.copy_ms
    record.release_wait_ms = timings.release_wait_ms
    record.release_timeout = timings.release_timeout
    if timings.copied:
        record.copied_words = record.final_words
    if timings.chord_sent:
        record.chord_words = record.final_words
        if record.stopped_at is not None:
            record.stop_to_chord_ms = (observed_at - record.stopped_at) * 1000


def apply_restore(record: UtteranceRecord | None, timings: DeliveryTimings | None) -> None:
    """Project the clipboard snapshot, original copy and restore. PURE.

    Separate from :func:`apply_delivery` so the restore, which runs after the
    chord and the delivered cue, never recomputes ``stop_to_chord_ms``.
    """
    if record is None or timings is None:
        return
    record.snapshot_ms = timings.snapshot_ms
    record.original_copied = timings.original_copied
    record.original_copy_ms = timings.original_copy_ms
    record.restore_ms = timings.restore_ms
    record.restored = timings.restored


def analytics_metrics(record: UtteranceRecord) -> dict[str, int | float | bool]:
    """Only measurements cross the durable-history boundary; never strings or IDs."""
    from dataclasses import fields

    excluded = {"utt", "started_at", "stopped_at"}
    return {
        field.name: value
        for field in fields(record)
        if field.name not in excluded
        and isinstance(value := getattr(record, field.name), (int, float, bool))
    }


def summary_fields(record: UtteranceRecord) -> dict[str, object]:
    """Render *record* as the summary line's ordered fields. PURE.

    Durations are rounded here rather than at each measuring site, so every
    phase records raw ``perf_counter`` arithmetic and only the line decides how
    much precision is worth reading. Flags become ``0``/``1`` to match the rest
    of the log; ``None`` stays ``None`` for ``fmt_event`` to drop.
    """
    return {
        "utt": record.utt,
        "source": record.source,
        "mode": record.mode,
        "outcome": record.outcome,
        "activate_ms": _ms(record.activate_ms),
        "press_to_callback_ms": _ms(record.press_to_callback_ms),
        "activation_to_callback_ms": _ms(record.activation_to_callback_ms),
        "capture_s": _seconds(record.capture_s),
        "in_frames": record.in_frames,
        "out_frames": record.out_frames,
        "capped": _flag(record.capped),
        "peak_rms": None if record.peak_rms is None else round(record.peak_rms, 6),
        "cold": _flag(record.cold),
        "load_ms": _ms(record.load_ms),
        "lock_wait_ms": _ms(record.lock_wait_ms),
        "decode_ms": _ms(record.decode_ms),
        "vad_frames": record.vad_frames,
        "segments": record.segments,
        "words": record.words,
        "chars_raw": record.chars_raw,
        "chars_out": record.chars_out,
        "refine": _flag(record.refine_applied),
        "refine_ms": _ms(record.refine_ms),
        "refine_failed": _flag(record.refine_failed),
        "copy_ms": _ms(record.copy_ms),
        "release_wait_ms": _ms(record.release_wait_ms),
        "release_timeout": _flag(record.release_timeout),
        "snapshot_ms": _ms(record.snapshot_ms),
        "original_copied": _flag(record.original_copied),
        "original_copy_ms": _ms(record.original_copy_ms),
        "restore_ms": _ms(record.restore_ms),
        "restored": _flag(record.restored),
        "total_ms": _ms(record.total_ms),
    }


def log_summary(record: UtteranceRecord) -> None:
    """Emit the one INFO line that describes the whole utterance."""
    log.info(fmt_event("pipeline", "utterance", **summary_fields(record)))


def downmix(samples: np.ndarray) -> np.ndarray:
    """Reduce a 2-D capture to mono by keeping channel 0. PURE.

    Channel 0, not the channel mean: averaging a stereo mic whose second
    channel is silent or out of phase halves or cancels the speech the VAD
    then has to find.
    """
    if samples.ndim != 2:
        return samples.reshape(-1)
    return samples[:, 0]


def transcript_text(result: TranscriptionResult, *, raw: bool = False) -> str:
    """Format a decode result for delivery. PURE.

    The trailing space belongs to dictation: consecutive utterances pasted at
    the cursor must not run together. ``raw`` hands back exactly what the
    decoder produced.
    """
    if raw:
        return result.text
    return format_transcript(result.text, trailing_space=True)


def _flag(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _seconds(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
