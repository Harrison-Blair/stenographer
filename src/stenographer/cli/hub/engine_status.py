# SPDX-License-Identifier: GPL-3.0-or-later
"""One snapshot of the engine status in the top bar."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineStatus:
    """Model, state and gauges; a gauge is ``None`` before its sample."""

    model: str
    state: str
    cpu_app_percent: float | None
    ram_app_bytes: int | None
