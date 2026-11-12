# SPDX-License-Identifier: GPL-3.0-or-later
"""The size tiers of the hub: wide, medium and narrow by terminal width."""

from __future__ import annotations

FLOOR_WIDTH = 60
FLOOR_HEIGHT = 16
TIERS = ("wide", "medium", "narrow")


def tier_for(width: int) -> str:
    """Return ``wide`` (120+ columns), ``medium`` (80 to 119) or ``narrow`` (less)."""
    if width >= 120:
        return "wide"
    return "medium" if width >= 80 else "narrow"


def below_floor(width: int, height: int) -> bool:
    """Return whether the terminal is smaller than 60x16."""
    return width < FLOOR_WIDTH or height < FLOOR_HEIGHT
