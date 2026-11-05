# SPDX-License-Identifier: GPL-3.0-or-later
"""Recognition segments, words, and result measurements."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WordInfo:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class SegmentInfo:
    start: float
    end: float
    text: str
    words: list[WordInfo] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: float
    segments: list[SegmentInfo] = field(default_factory=list)
    #: Seconds of audio the VAD kept. Carried back to the parent so the
    #: utterance summary can report it without a second decode-side log line.
    vad_seconds: float = 0.0
    inference_ms: float | None = None


@dataclass(frozen=True)
class WorkerTimings:
    """How one ``transcribe`` call spent its wall clock, in milliseconds.

    ``decode_ms`` is measured inside the child around inference; ``round_trip_ms``
    includes request/response transport. Failed phases retain elapsed boundaries
    while unobserved inference remains unknown. ``load_ms`` is absent on a warm
    model; concurrent press-lazy warm-up is measured separately by the daemon.
    """

    lock_wait_ms: float
    load_ms: float | None
    decode_ms: float | None
    round_trip_ms: float | None = None
