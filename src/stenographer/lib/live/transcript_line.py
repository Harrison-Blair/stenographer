# SPDX-License-Identifier: GPL-3.0-or-later
"""One recognized phrase in a live session."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptLine:
    start: float
    end: float
    wall: str
    source: str
    speaker_id: str
    label: str
    text: str
