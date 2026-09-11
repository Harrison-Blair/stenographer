# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decode sizing, output validation, and transcript assembly."""

from __future__ import annotations

import math

from stenographer.lib.transcribe.errors import PathologicalOutputError
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult

_WORDS_PER_VAD_SECOND = 8


_MIN_WORD_LIMIT = 12


_AUTO_CPU_THREAD_CAP = 8


_CPU_THREAD_FALLBACK = 4


def resolve_cpu_threads(configured: int, physical_cores: int | None) -> int:
    """Explicit value passes through; else *physical_cores* capped at eight,
    falling back to four when the host could not count them."""
    if configured:
        return configured
    if physical_cores is None or physical_cores < 1:
        return _CPU_THREAD_FALLBACK
    return min(_AUTO_CPU_THREAD_CAP, physical_cores)


def _token_budget(configured_max: int, audio_seconds: float) -> int:
    """Bound generated tokens to a small fixed allowance plus audio duration."""
    return min(configured_max, 16 + math.ceil(_WORDS_PER_VAD_SECOND * audio_seconds))


def _validate_output(
    *,
    segment_timestamps: list[tuple[float, float]],
    word_timestamps: list[tuple[float, float]],
    word_count: int,
    audio_seconds: float,
    vad_seconds: float,
) -> None:
    """Reject invalid timestamps and decoder-runaway word density. Messages carry
    no transcript content so pathological output never leaks dictated text."""
    if not math.isfinite(vad_seconds) or vad_seconds < 0:
        raise PathologicalOutputError("invalid VAD duration")
    tolerance = 1.0
    for start, end in (*segment_timestamps, *word_timestamps):
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or end > audio_seconds + tolerance
        ):
            raise PathologicalOutputError("invalid decoder timestamp")
    word_limit = max(_MIN_WORD_LIMIT, math.ceil(_WORDS_PER_VAD_SECOND * vad_seconds))
    if word_count > word_limit:
        raise PathologicalOutputError(
            f"decoder word density exceeded limit ({word_count} > {word_limit})"
        )


def _assemble(
    segments: list[SegmentInfo],
    *,
    silence_threshold: float,
    audio_seconds: float,
    vad_seconds: float,
) -> TranscriptionResult:
    """Gate probable-silence segments, validate, and assemble the transcript."""
    kept = [seg for seg in segments if seg.no_speech_prob < silence_threshold]
    text = "".join(seg.text for seg in kept).strip()
    word_timestamps = [(w.start, w.end) for seg in kept for w in seg.words]
    _validate_output(
        segment_timestamps=[(seg.start, seg.end) for seg in kept],
        word_timestamps=word_timestamps,
        word_count=len(word_timestamps),
        audio_seconds=audio_seconds,
        vad_seconds=vad_seconds,
    )
    return TranscriptionResult(
        text=text, duration_seconds=audio_seconds, segments=kept, vad_seconds=vad_seconds
    )
