# SPDX-License-Identifier: GPL-3.0-or-later
"""A dialog button that marks keyboard focus with a glyph."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Button


class FocusButton(Button):
    """Print ``▶`` before the label while focused, so focus shows without colour.

    The unfocused label keeps two blank cells there, so focus moves no button.
    """

    def __init__(self, label: str | Text, **kwargs) -> None:
        self.plain_label = label.copy() if isinstance(label, Text) else Text(label)
        super().__init__(self.marked_label(focused=False), **kwargs)

    def marked_label(self, *, focused: bool) -> Text:
        return Text("▶ " if focused else "  ").append_text(self.plain_label)

    def on_focus(self) -> None:
        self.label = self.marked_label(focused=True)

    def on_blur(self) -> None:
        self.label = self.marked_label(focused=False)
