# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from enum import StrEnum


class OverlayState(StrEnum):
    HIDDEN = "hidden"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    DELIVERING = "delivering"
    CANCELLED = "cancelled"
    ERROR = "error"
