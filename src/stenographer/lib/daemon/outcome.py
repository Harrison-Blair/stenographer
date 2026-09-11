# SPDX-License-Identifier: GPL-3.0-or-later
"""The existing terminal pipeline outcome vocabulary."""

from __future__ import annotations

from enum import Enum, auto


class Outcome(Enum):
    SILENT = auto()
    DELIVERED = auto()
    ERROR = auto()
