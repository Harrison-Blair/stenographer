# SPDX-License-Identifier: GPL-3.0-or-later
"""One row of key hints for a footer or the last row of a panel."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

_ACCENT = "bold #5fd7ff"
_DIM = "#8b93a1"


class KeyHints(Static):
    """Show ``key description`` items; a footer always ends with help and quit."""

    DEFAULT_CSS = """
    KeyHints {
        width: 1fr;
        height: 1;
        padding: 0 2;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    KeyHints.-panel {
        padding: 0;
        text-align: right;
    }
    """
    FOOTER_END = (("?", "help"), ("q", "quit"))

    def __init__(self, *, footer: bool = True, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.footer = footer
        self.items: tuple[tuple[str, str], ...] = ()
        if not footer:
            self.add_class("-panel")

    def set_hints(self, *items: tuple[str, str], end: bool = True) -> None:
        """Show the items; a footer row appends ``? help · q quit`` unless ``end`` is false."""
        if self.footer:
            items = tuple(item for item in items if item not in self.FOOTER_END)
            if end:
                items += self.FOOTER_END
        self.items = items
        self.update(self.hint_text(items, footer=self.footer))

    @staticmethod
    def hint_text(items: tuple[tuple[str, str], ...], *, footer: bool) -> Text:
        """Return the hint row with dots between items."""
        text = Text(no_wrap=True)
        for index, (key, description) in enumerate(items):
            if index:
                text.append(" · ", style=_DIM)
            text.append(key, style=_ACCENT if footer else _DIM)
            text.append(f" {description}", style=_DIM if not footer else "default")
        return text
