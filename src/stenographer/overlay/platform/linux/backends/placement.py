# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from stenographer.overlay.platform.linux.backends.monitor import Monitor


@dataclass(frozen=True, slots=True)
class Placement:
    """Monitor and scale frozen for one hidden-to-visible interval."""

    monitor: Monitor
    scale: float
