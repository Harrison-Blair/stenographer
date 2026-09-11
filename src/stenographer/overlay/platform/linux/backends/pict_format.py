# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PictFormat:
    """The RENDER fields needed to prove a visual has an alpha channel."""

    format_id: int
    format_type: int
    depth: int
    alpha_shift: int
    alpha_mask: int
