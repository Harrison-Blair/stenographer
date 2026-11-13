# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library table: one entry on two lines, columns by size tier."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.widgets import Static

from stenographer.cli.hub.widgets.row_selected import RowSelected
from stenographer.cli.hub.widgets.update_changed import update_changed

_ACCENT_BOLD = "bold #5fd7ff"
_DIM = "#8b93a1"
_MARKER = 2
ELLIPSIS = "…"


@dataclass(frozen=True)
class Column:
    """One column: the cells of its value, the gap after it, and the alignment."""

    name: str
    width: int
    gap: int = 0
    right: bool = False


# A width of 0 is the title: it takes the cells that the others leave.
COLUMNS: dict[str, tuple[Column, ...]] = {
    "wide": (
        Column("date", 12, 1),
        Column("dur", 8, 2, right=True),
        Column("kind", 4, 2),
        Column("speakers", 22, 2),
        Column("title", 0, 1),
        Column("size", 7, 2, right=True),
        Column("state", 13),
    ),
    "medium": (
        Column("date", 12, 1),
        Column("dur", 8, 2, right=True),
        Column("speakers", 16, 2),
        Column("title", 0),
        Column("glyph", 2, right=True),
    ),
    "narrow": (
        Column("date", 12, 1),
        Column("dur", 8, 1, right=True),
        Column("title", 0),
        Column("glyph", 2, right=True),
    ),
}
_HEADINGS = {"glyph": ""}


@dataclass(frozen=True)
class TableRow:
    """The cells of one entry; the table picks the columns of its tier."""

    date: str
    dur: Text
    kind: str
    speakers: tuple[str, ...]
    # The title, the file name of a file entry without a title, or ``None``.
    title: str | None
    size: Text
    state: Text
    glyph: Text


def title_width(tier: str, width: int) -> int:
    """Return the cells of the title column in a table ``width`` cells wide."""
    fixed = sum(column.width + column.gap for column in COLUMNS[tier])
    return max(1, width - _MARKER - fixed)


def cut(text: str, width: int) -> str:
    """Return ``text`` in at most ``width`` cells; a cut ends with ``…``."""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)].rstrip() + ELLIPSIS


def two_lines(text: str, width: int) -> tuple[str, str]:
    """Wrap ``text`` into two lines of ``width`` cells; the second ends with ``…`` when cut."""
    lines = textwrap.wrap(text, width) or [""]
    if len(lines) <= 2:
        return lines[0], lines[1] if len(lines) == 2 else ""
    return lines[0], cut(" ".join(lines[1:]), width)


def speaker_lines(names: tuple[str, ...], width: int) -> tuple[str, ...]:
    """Return the names on at most two lines; ``+N`` counts the names that do not fit."""
    names = tuple(cut(name, max(1, width - 1)) for name in names)
    for shown in range(len(names), -1, -1):
        hidden = len(names) - shown
        tokens = [f"{name}," for name in names[:shown]]
        if tokens:
            tokens[-1] = tokens[-1].removesuffix(",")
        if hidden:
            tokens.append(f"+{hidden}")
        lines = _flow(tokens, width)
        if len(lines) <= 2:
            return tuple(lines)
    return ()


def _flow(tokens: list[str], width: int) -> list[str]:
    lines: list[str] = []
    for token in tokens:
        if lines and len(lines[-1]) + 1 + len(token) <= width:
            lines[-1] += f" {token}"
        else:
            lines.append(token)
    return lines


class LibraryTable(Static):
    """Show each entry on two lines; a click selects an entry and posts ``RowSelected``."""

    DEFAULT_CSS = """
    LibraryTable {
        height: auto;
        text-wrap: nowrap;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.rows: tuple[TableRow, ...] = ()
        self.selected_index: int | None = None
        self.message: Text | None = None
        self.tier = "wide"

    def set_rows(
        self,
        rows: tuple[TableRow, ...],
        selected_index: int | None,
        *,
        tier: str,
        message: Text | None = None,
    ) -> None:
        self.rows = rows
        self.selected_index = selected_index
        self.tier = tier
        self.message = message
        update_changed(self, self.table_text(self.size.width))

    def on_resize(self) -> None:
        update_changed(self, self.table_text(self.size.width))

    @staticmethod
    def heading(tier: str, width: int) -> Text:
        """Return the column names, each over its column."""
        text = Text(" " * _MARKER, no_wrap=True, style=_DIM)
        for column in COLUMNS[tier]:
            cells = column.width or title_width(tier, width)
            name = _HEADINGS.get(column.name, column.name)
            text.append(name.rjust(cells) if column.right else name.ljust(cells))
            text.append(" " * column.gap)
        return text

    def table_text(self, width: int) -> Text:
        text = Text(no_wrap=True)
        for index, row in enumerate(self.rows):
            if index:
                text.append("\n")
            first, second = self._row_lines(row, width, selected=index == self.selected_index)
            text.append_text(first)
            text.append("\n")
            text.append_text(second)
        if self.message is not None:
            if self.rows:
                text.append("\n")
            text.append(" " * _MARKER)
            text.append_text(self.message)
        return text

    def _row_lines(self, row: TableRow, width: int, *, selected: bool) -> tuple[Text, Text]:
        first = Text("▶ " if selected else "  ", style=_ACCENT_BOLD if selected else None)
        second = Text(" " * _MARKER)
        for column in COLUMNS[self.tier]:
            cells = column.width or title_width(self.tier, width)
            top, bottom = self._cell(row, column.name, cells)
            for line, value in ((first, top), (second, bottom)):
                pad = " " * max(0, cells - value.cell_len)
                if column.right:
                    line.append(pad)
                    line.append_text(value)
                else:
                    line.append_text(value)
                    line.append(pad)
                line.append(" " * column.gap)
        if selected:
            first.stylize("bold", _MARKER)
            second.stylize("bold")
        return first, second

    def _cell(self, row: TableRow, name: str, cells: int) -> tuple[Text, Text]:
        empty = Text("")
        if name == "date":
            return Text(row.date), empty
        if name == "dur":
            return row.dur, empty
        if name == "kind":
            return Text(row.kind), empty
        if name == "size":
            return row.size, empty
        if name == "state":
            return row.state, empty
        if name == "glyph":
            return row.glyph, empty
        if name == "speakers":
            return self._speakers(row.speakers, cells)
        if row.title is None:
            if self.tier == "narrow" and row.speakers:
                top, bottom = two_lines(", ".join(row.speakers), cells)
                return Text(top, style=_DIM), Text(bottom, style=_DIM)
            return Text("—", style=_DIM), empty
        top, bottom = two_lines(row.title, cells)
        return Text(top), Text(bottom)

    @staticmethod
    def _speakers(names: tuple[str, ...], cells: int) -> tuple[Text, Text]:
        if not names:
            return Text("—", style=_DIM), Text("")
        lines = speaker_lines(names, cells)
        texts = [Text(line) for line in lines] + [Text("")] * (2 - len(lines))
        for text in texts:
            text.highlight_regex(r"\+\d+$", _DIM)
        return texts[0], texts[1]

    def on_click(self, event: events.Click) -> None:
        index = event.y // 2
        if 0 <= index < len(self.rows):
            self.post_message(RowSelected(self, index))
