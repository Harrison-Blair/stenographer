# SPDX-License-Identifier: GPL-3.0-or-later
"""Retained audio-stream lifecycle states."""

from __future__ import annotations

from enum import Enum, auto


class RecorderState(Enum):
    """PortAudio lifecycle state for :class:`Recorder`."""

    UNPREPARED = auto()
    PREPARED = auto()
    CAPTURING = auto()
