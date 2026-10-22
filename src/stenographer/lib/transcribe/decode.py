# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure decode sizing, token-to-word mapping, output validation, and assembly."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.transcribe.errors import PathologicalOutputError
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult, WordInfo

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

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


#: SentencePiece word marker; sherpa may also hand it back as a plain space.
_WORD_MARKER = "\u2581"


_UNKNOWN_TOKEN = "<unk>"


def pad_samples(samples: np.ndarray, pad_seconds: float) -> np.ndarray:
    """Prepend *pad_seconds* of digital silence to a mono float32 buffer. PURE."""
    import numpy as np

    pad = np.zeros(round(pad_seconds * SAMPLE_RATE), dtype=np.float32)
    return np.concatenate([pad, np.asarray(samples, dtype=np.float32)])


def words_from_tokens(
    tokens: Sequence[str],
    timestamps: Sequence[float],
    durations: Sequence[float],
    log_probs: Sequence[float],
    *,
    offset: float,
) -> list[WordInfo]:
    """Join sherpa tokens into words at the word marker. PURE.

    A token spans its timestamp plus its predicted TDT duration (none: a point).
    Times shift back by *offset* (the leading pad) and clamp at zero. A token
    without letters or digits joins the previous word without widening its span.
    ``probability`` is exp of the mean token log-prob, or 1.0 when the log-probs
    do not align with the tokens; it is information only.
    """
    spans = list(durations) if len(durations) == len(tokens) else [0.0] * len(tokens)
    scores = list(log_probs) if len(log_probs) == len(tokens) else None
    words: list[tuple[float, float, str, list[float]]] = []
    starts_word = True
    for index, token in enumerate(tokens):
        if token == _UNKNOWN_TOKEN:
            continue
        text = token.replace(_WORD_MARKER, " ")
        piece = text.strip()
        starts_word = starts_word or text.startswith(" ")
        if not piece:
            continue
        start = max(0.0, timestamps[index] - offset)
        end = max(start, timestamps[index] + spans[index] - offset)
        score = [scores[index]] if scores is not None else []
        if starts_word or not words:
            words.append((start, end, piece, score))
        else:
            first, last, joined, previous = words[-1]
            if any(ch.isalnum() for ch in piece):
                last = max(last, end)
            words[-1] = (first, last, joined + piece, previous + score)
        starts_word = False
    return [
        WordInfo(start, end, word, math.exp(sum(score) / len(score)) if score else 1.0)
        for start, end, word, score in words
    ]


def decode_segments(text: str, words: list[WordInfo]) -> list[SegmentInfo]:
    """The one segment of a decode, or none when its text is empty. PURE."""
    cleaned = " ".join(text.replace(_UNKNOWN_TOKEN, " ").split())
    if not cleaned:
        return []
    start, end = (words[0].start, words[-1].end) if words else (0.0, 0.0)
    return [SegmentInfo(start=start, end=end, text=cleaned, words=words)]


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
    audio_seconds: float,
    vad_seconds: float,
) -> TranscriptionResult:
    """Validate the segments and assemble the transcript."""
    text = "".join(seg.text for seg in segments).strip()
    word_timestamps = [(w.start, w.end) for seg in segments for w in seg.words]
    _validate_output(
        segment_timestamps=[(seg.start, seg.end) for seg in segments],
        word_timestamps=word_timestamps,
        word_count=len(word_timestamps),
        audio_seconds=audio_seconds,
        vad_seconds=vad_seconds,
    )
    return TranscriptionResult(
        text=text, duration_seconds=audio_seconds, segments=segments, vad_seconds=vad_seconds
    )
