# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from enum import StrEnum


class DisplayIntent(StrEnum):
    """What a backend must do to its own surface after one accepted record."""

    NONE = "none"
    REDRAW = "redraw"
    REPAINT = "repaint"
    """Repaint an existing surface only — a frame update never creates one."""
    TEARDOWN = "teardown"
    STOP = "stop"
