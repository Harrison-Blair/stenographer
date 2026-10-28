# SPDX-License-Identifier: GPL-3.0-or-later
"""One snapshot of the sidebar engine card."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineStatus:
    """Model, state line, gauges and app CPU history; a gauge is ``None`` before its sample."""

    model: str
    state: str
    cpu_app_percent: float | None
    cpu_all_percent: float | None
    ram_app_bytes: int | None
    cpu_history: tuple[float, ...]
