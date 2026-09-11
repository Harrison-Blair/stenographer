# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from enum import StrEnum


class GlobalRemoval(StrEnum):
    """What losing one advertised global means for a running surface."""

    IGNORE = "ignore"
    LOST = "lost"
    OUTPUT = "output"
