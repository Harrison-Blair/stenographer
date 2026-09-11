# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True, slots=True)
class OverlayFrame:
    """One scaled frame and the physical-pixel bounds of its visible pill."""

    image: Image.Image
    scale: float
    pill_bounds: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def stride(self) -> int:
        return self.image.width * 4
