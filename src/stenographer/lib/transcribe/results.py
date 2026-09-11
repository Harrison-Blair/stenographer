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
    no_speech_prob: float
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
