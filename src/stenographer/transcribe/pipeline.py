# SPDX-License-Identifier: GPL-3.0-or-later
"""The gate → decode → format core shared by the daemon and ``transcribe``.

One utterance produces exactly one INFO summary line, whether it came from the
hotkey or from ``stenographer transcribe <file>``. Both paths fill the same
:class:`UtteranceRecord` as their phases complete and hand it to
:func:`log_summary`, so a file run is directly comparable with a live one; both
also downmix through :func:`downmix` and format through :func:`transcript_text`,
so neither can drift from the other's audio or spacing.

The record is filled in from several threads (hotkey, pipeline) but only ever
for the one utterance in flight, which the daemon's state lock serialises.
:func:`summary_fields`, :func:`downmix` and :func:`transcript_text` are pure;
the two ``log_*`` helpers exist so the ``fmt_event`` call sites stay literal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.analytics import count_words
from stenographer.constants import SAMPLE_RATE
from stenographer.transcribe.format import format_transcript
from stenographer.utils.logging_setup import fmt_event

if TYPE_CHECKING:
    import numpy as np

    from stenographer.audio import CaptureStats, GateStats
    from stenographer.delivery.deliver import DeliveryTimings
    from stenographer.transcribe.model import TranscriptionResult
    from stenographer.transcribe.worker import WorkerTimings

log = logging.getLogger(__name__)


@dataclass
class UtteranceRecord:
    """Everything measured about one utterance, in summary-line order.

    Every field but ``utt`` is optional: an utterance that fails its gate never
    reaches a decode, and a rendered ``None`` field is dropped rather than
    printed, so one record serves every early exit.
    """

    utt: int
    #: ``perf_counter`` at the moment this utterance was accepted. On the
    #: record, not on the daemon: the summary is rendered after the state lock
    #: is handed on, and a process-global origin would already belong to the
    #: next utterance after a fast re-press.
    started_at: float = 0.0
    source: str | None = None
    mode: str | None = None
    outcome: str | None = None
    activate_ms: float | None = None
    press_to_callback_ms: float | None = None
    activation_to_callback_ms: float | None = None
    max_adc_gap_ms: float | None = None
    adc_discontinuities: int | None = None
    capture_s: float | None = None
    in_frames: int | None = None
    out_frames: int | None = None
    overflow: bool | None = None
    capped: bool | None = None
    gate: str | None = None
    peak_rms: float | None = None
    frames_above: int | None = None
    cold: bool | None = None
    load_ms: float | None = None
    lock_wait_ms: float | None = None
    decode_ms: float | None = None
    vad_frames: int | None = None
    segments: int | None = None
    words: int | None = None
    chars_raw: int | None = None
    chars_out: int | None = None
    copy_ms: float | None = None
    release_wait_ms: float | None = None
    release_timeout: bool | None = None
    total_ms: float | None = None
    analytics_id: str | None = None
    device_name: str | None = None
    stopped_at: float | None = None
    recognized_words: int | None = None
    final_words: int | None = None
    copied_words: int | None = None
    chord_words: int | None = None
    asr_audio_s: float | None = None
    vad_s: float | None = None
    format_ms: float | None = None
    round_trip_ms: float | None = None
    finalize_ms: float | None = None
    stop_to_ready_ms: float | None = None
    stop_to_chord_ms: float | None = None
    input_rate: int | None = None
    channels: int | None = None
    callback_timing_count: int | None = None
    callback_count: int | None = None
    callback_metadata_dropped: int | None = None
    overflow_count: int | None = None
    recovered: bool | None = None
    mean_rms: float | None = None
    clipping_fraction: float | None = None
    ignored_busy_presses: int = 0
    failure: str | None = None


def apply_capture(record: UtteranceRecord | None, stats: CaptureStats | None) -> None:
    """Project secured recorder measurements without sampling a clock. PURE."""
    if record is None or stats is None:
        return
    record.activate_ms = stats.activate_ms
    if stats.first_callback_at is not None:
        record.press_to_callback_ms = (stats.first_callback_at - record.started_at) * 1000
    record.activation_to_callback_ms = stats.activation_to_callback_ms
    record.max_adc_gap_ms = stats.max_adc_gap_ms
    record.adc_discontinuities = stats.adc_discontinuities
    record.capture_s = stats.input_frames / stats.input_rate
    record.device_name = stats.device_name
    record.input_rate = stats.input_rate
    record.channels = stats.channels
    record.finalize_ms = stats.finalize_ms
    record.callback_timing_count = stats.callback_timing_count
    record.callback_count = stats.callback_count
    record.callback_metadata_dropped = stats.callback_metadata_dropped
    record.overflow_count = stats.overflow_count
    record.recovered = stats.recovered
    record.in_frames = stats.input_frames
    record.out_frames = stats.output_frames
    record.overflow = stats.overflow
    record.capped = stats.capped


def apply_gate(record: UtteranceRecord | None, stats: GateStats, samples: np.ndarray) -> None:
    """Project one gate verdict and its diagnostic measurements. PURE."""
    if record is None:
        return
    import numpy as np

    record.gate = "pass" if stats.passed else "fail"
    record.peak_rms = stats.peak_rms
    record.frames_above = stats.frames_above
    record.mean_rms = stats.mean_rms
    record.clipping_fraction = float(np.mean(np.abs(samples) >= 0.999)) if samples.size else 0.0


def apply_recognition(record: UtteranceRecord | None, result: TranscriptionResult) -> None:
    """Keep accepted recognition even when a subsequent phase fails. PURE."""
    if record is None:
        return
    record.vad_frames = round(result.vad_seconds * SAMPLE_RATE)
    record.segments = len(result.segments)
    record.words = sum(len(segment.words) for segment in result.segments)
    record.chars_raw = len(result.text)
    record.recognized_words = count_words(result.text)
    record.asr_audio_s = record.capture_s
    record.vad_s = result.vad_seconds


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
        "max_adc_gap_ms": _ms(record.max_adc_gap_ms),
        "adc_discontinuities": record.adc_discontinuities,
        "capture_s": _seconds(record.capture_s),
        "in_frames": record.in_frames,
        "out_frames": record.out_frames,
        "overflow": _flag(record.overflow),
        "capped": _flag(record.capped),
        "gate": record.gate,
        "peak_rms": None if record.peak_rms is None else round(record.peak_rms, 6),
        "frames_above": record.frames_above,
        "cold": _flag(record.cold),
        "load_ms": _ms(record.load_ms),
        "lock_wait_ms": _ms(record.lock_wait_ms),
        "decode_ms": _ms(record.decode_ms),
        "vad_frames": record.vad_frames,
        "segments": record.segments,
        "words": record.words,
        "chars_raw": record.chars_raw,
        "chars_out": record.chars_out,
        "copy_ms": _ms(record.copy_ms),
        "release_wait_ms": _ms(record.release_wait_ms),
        "release_timeout": _flag(record.release_timeout),
        "total_ms": _ms(record.total_ms),
    }


def log_summary(record: UtteranceRecord) -> None:
    """Emit the one INFO line that describes the whole utterance."""
    log.info(fmt_event("pipeline", "utterance", **summary_fields(record)))


def log_gate(stats: GateStats) -> None:
    """Report the energy gate's numbers and its verdict from one computation."""
    log.info(
        fmt_event(
            "audio",
            "speech_gate",
            verdict="pass" if stats.passed else "fail",
            peak_rms=round(stats.peak_rms, 6),
            mean_rms=round(stats.mean_rms, 6),
            frames_total=stats.frames_total,
            frames_above=stats.frames_above,
            threshold=stats.threshold,
        )
    )


def downmix(samples: np.ndarray) -> np.ndarray:
    """Reduce a 2-D capture to mono by keeping channel 0. PURE.

    Channel 0, not the channel mean: that is what the PortAudio callback keeps,
    and averaging a stereo mic whose second channel is silent or out of phase
    halves or cancels the speech the gate then has to find.
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
