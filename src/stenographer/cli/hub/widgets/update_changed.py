# SPDX-License-Identifier: GPL-3.0-or-later
"""Update a Static only on a change: each update asks Textual to lay out the whole screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import RenderableType
    from textual.widgets import Static


def update_changed(widget: Static, content: RenderableType) -> None:
    """Show ``content`` unless it is already shown. ``Text`` equality ignores the base style."""
    shown = widget.content
    if shown != content or getattr(shown, "style", None) != getattr(content, "style", None):
        widget.update(content)
