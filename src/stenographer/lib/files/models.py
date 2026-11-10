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
    refine: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser())


@dataclass(frozen=True)
class FileJobProgress:
    """Current visible stage and preview for one job."""

    stage: str
    percent: int
    completed_lines: tuple[TranscriptLine, ...]
