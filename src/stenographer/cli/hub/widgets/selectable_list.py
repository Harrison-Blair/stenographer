# SPDX-License-Identifier: GPL-3.0-or-later
"""A list of one-line rows; the selected row is bold accent with ``▶``."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.widgets import Static

from stenographer.cli.hub.widgets.row_selected import RowSelected

_ACCENT_BOLD = "bold #5fd7ff"


class SelectableList(Static):
    """Show rows that never wrap; a click selects a row and posts ``RowSelected``.

    Each row is a main cell and an optional end cell (a badge or a status).
    The main cell is cut with an ellipsis so the end cell always shows.
    """

    DEFAULT_CSS = """
    SelectableList {
        height: auto;
        text-wrap: nowrap;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.rows: tuple[tuple[str | Text, str | Text], ...] = ()
        self.selected_index: int | None = None

    def set_rows(
        self,
        rows: tuple[tuple[str | Text, str | Text], ...],
        selected_index: int | None = None,
    ) -> None:
        """Show ``(main, end)`` rows and mark one as selected."""
        self.rows = tuple(rows)
        self.selected_index = selected_index
        self.update(self.rows_text(self.size.width))

    def on_resize(self) -> None:
        self.update(self.rows_text(self.size.width))

    def rows_text(self, width: int) -> Text:
        text = Text(no_wrap=True)
        for index, (main, end) in enumerate(self.rows):
            if index:
                text.append("\n")
            selected = index == self.selected_index
            style = _ACCENT_BOLD if selected else None
            text.append("▶ " if selected else "  ", style=style)
            main_text = main.copy() if isinstance(main, Text) else Text(main)
            end_text = end.copy() if isinstance(end, Text) else Text(end)
            room = max(1, width - 2 - (cell_len(end_text.plain) + 1 if end_text.plain else 0))
            if width and main_text.cell_len > room:
                main_text.truncate(room, overflow="ellipsis")
            if selected:
                main_text.stylize(_ACCENT_BOLD)
            text.append_text(main_text)
            if end_text.plain:
                gap = max(1, (width or 0) - 2 - main_text.cell_len - end_text.cell_len)
                text.append(" " * gap)
                text.append_text(end_text)
        return text

    def on_click(self, event: events.Click) -> None:
        index = event.y + int(self.scroll_offset.y)
        if 0 <= index < len(self.rows):
            self.selected_index = index
            self.update(self.rows_text(self.size.width))
            self.post_message(RowSelected(self, index))
