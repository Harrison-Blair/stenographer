# SPDX-License-Identifier: GPL-3.0-or-later
"""One row of key hints for a footer or the last row of a panel."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from stenographer.cli.hub.widgets.update_changed import update_changed

_ACCENT = "bold #5fd7ff"
_DIM = "#8b93a1"


class KeyHints(Static):
    """Show ``key description`` items; a footer starts with help and quit.

    Whole items drop from the right until the row fits; ``? help`` always stays.
    """

    DEFAULT_CSS = """
    KeyHints {
        width: 1fr;
        height: 1;
        padding: 0 1;
        text-wrap: nowrap;
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
        """Show the items; a footer row starts with ``? help · q quit`` unless ``end`` is false."""
        if self.footer:
            items = tuple(item for item in items if item not in self.FOOTER_END)
            if end:
                items = self.FOOTER_END + items
        self.items = items
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def _draw(self) -> None:
        update_changed(
            self,
            self.hint_text(self.fitting(self.items, self.content_size.width), footer=self.footer),
        )

    def fitting(
        self, items: tuple[tuple[str, str], ...], width: int
    ) -> tuple[tuple[str, str], ...]:
        """Return the items that fit ``width`` cells; whole items drop from the right.

        The first item stays, so a footer keeps ``? help``.
        """
        kept = list(items)
        while width and len(kept) > 1 and self.hint_text(tuple(kept), footer=True).cell_len > width:
            kept.pop()
        return tuple(kept)

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
