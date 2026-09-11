# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Monitor:
    """One connected RandR output, or the root fallback when output is None."""

    output: int | None
    x: int
    y: int
    width: int
    height: int
    primary: bool = False
    connected: bool = True
    millimeter_width: int = 0

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def contains(self, point: tuple[int, int]) -> bool:
        px, py = point
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height
