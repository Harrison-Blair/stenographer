# SPDX-License-Identifier: GPL-3.0-or-later
"""File job options and progress snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stenographer.lib.live.transcript_line import TranscriptLine


@dataclass(frozen=True)
class FileJobOptions:
    """One file transcription request."""

    path: Path
    diarize: bool = True
    speaker_count: int | None = None
    refine: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser())
        if self.speaker_count is not None and (
            isinstance(self.speaker_count, bool)
            or not isinstance(self.speaker_count, int)
            or self.speaker_count < 1
        ):
            raise ValueError("speaker_count must be a positive integer")


@dataclass(frozen=True)
class FileJobProgress:
    """Current visible stage and preview for one job."""

    stage: str
    percent: int
    eta_seconds: float | None
    completed_lines: tuple[TranscriptLine, ...]
