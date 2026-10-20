# SPDX-License-Identifier: GPL-3.0-or-later
"""Assign stable accent colors to speaker labels."""

from __future__ import annotations

MIC_SPEAKER_COLOR = "#5fd7ff"
SYSTEM_SPEAKER_COLORS = ("#ffaf5f", "#d787ff", "#87d787")


def speaker_color(
    speaker_id: str,
    speaker_ids: tuple[str, ...],
    *,
    source: str | None = None,
) -> str:
    """Return the accent color for one speaker in the supplied stable order."""
    if source == "mic" or speaker_id == "you":
        return MIC_SPEAKER_COLOR
    system_ids = tuple(current for current in speaker_ids if current != "you")
    try:
        index = system_ids.index(speaker_id)
    except ValueError:
        index = 0
    return SYSTEM_SPEAKER_COLORS[index % len(SYSTEM_SPEAKER_COLORS)]
