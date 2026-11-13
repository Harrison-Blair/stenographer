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
    # A file job kept its tracker labels because its speaker pass failed.
    speaker_pass_failed: bool = False
    # Speaker names, most talk time first.
    speakers: tuple[str, ...] = ()
    title: str | None = None
    # ``model`` or ``user``; ``None`` when the session has no title.
    title_source: str | None = None


@dataclass(frozen=True)
class SessionDetail:
    summary: SessionSummary
    lines: tuple[TranscriptLine, ...]
    talk_time: dict[str, float]
    revision: str
    diarize_mic: bool = False
    # A file session's speaker option; ``None`` for a session older than the record.
    diarize: bool | None = None
