# SPDX-License-Identifier: GPL-3.0-or-later
"""Render selectable rows without a background fill."""

from __future__ import annotations

from rich.text import Text

_ACCENT_BOLD = "bold #5fd7ff"


def append_line(
    text: Text,
    value: str,
    *,
    selectable: bool = False,
    selected: bool = False,
) -> None:
    """Append one line, with an accent marker when it is selected."""
    if text:
        text.append("\n")
    style = _ACCENT_BOLD if selected else None
    if selectable:
        text.append("▶ " if selected else "  ", style=style)
    text.append(value, style=style)
