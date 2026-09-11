# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StackingReassertPlan:
    """Bounded delayed EWMH reassertions tied to one X window epoch."""

    epoch: int
    deadlines: tuple[float, ...]
