# SPDX-License-Identifier: GPL-3.0-or-later
"""Session summaries and loaded transcript data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stenographer.lib.live.transcript_line import TranscriptLine


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    started_at: datetime
    duration_seconds: float
    speaker_count: int
    audio_size_bytes: int
    interrupted: bool
    kind: str = "rec"
    source_name: str | None = None
    label_state: str = "live"


@dataclass(frozen=True)
class SessionDetail:
    summary: SessionSummary
    lines: tuple[TranscriptLine, ...]
    talk_time: dict[str, float]
    activity: dict[str, tuple[float, ...]]
    revision: str
    labels_revised: bool = False
    diarize_mic: bool = False
