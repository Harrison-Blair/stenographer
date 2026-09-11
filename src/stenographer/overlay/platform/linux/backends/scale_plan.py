# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScalePlan:
    """Renderer scale and Wayland surface mapping for one frame."""

    render_scale: float
    buffer_scale: int
    viewport_destination: tuple[int, int] | None
