# SPDX-License-Identifier: GPL-3.0-or-later
"""One transcript row: time, speaker and text, in mixed or split layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from stenographer.cli.hub.widgets.clock import Clock
from stenographer.cli.shared.speaker_colors import speaker_color

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rich.console import Console, ConsoleOptions, RenderResult

_DIM = "#8b93a1"


class TranscriptLine:
    """Render one transcript line; text wraps under its own column."""

    @staticmethod
    def row(
        start: float,
        label: str,
        text: str,
        *,
        color: str = "default",
        source: str = "mic",
        layout: str = "mixed",
    ) -> Table:
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=8, no_wrap=True)
        time = Text(Clock.format(start), style=_DIM)
        who_style = f"bold {color}"
        body = text.replace("\n", " ")
        if layout == "split":
            table.add_column(ratio=1)
            table.add_column(ratio=1)
            cell = Text()
            cell.append(label, style=who_style)
            cell.append(f"  {body}")
            dot = Text("·", style=_DIM)
            mic, system = (cell, dot) if source == "mic" else (dot, cell)
            table.add_row(time, mic, system)
        else:
            table.add_column(width=10, no_wrap=True, overflow="ellipsis")
            table.add_column(ratio=1)
            table.add_row(time, Text(label, style=who_style), Text(body))
        return table


class _RenderedRow:
    """Keep the segments of one row: Textual renders the whole transcript on each new line."""

    def __init__(self, table: Table) -> None:
        self._table = table
        self._width: int | None = None
        self._segments: tuple = ()

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if options.max_width != self._width:
            self._width = options.max_width
            self._segments = tuple(console.render(self._table, options))
        yield from self._segments


class TranscriptRows:
    """Make the rows of a transcript; a line with the same color and layout keeps its row."""

    def __init__(self) -> None:
        self._rows: dict[tuple, _RenderedRow] = {}

    def rows(
        self, lines: Iterable, speaker_ids: tuple[str, ...], *, layout: str = "mixed"
    ) -> list[_RenderedRow]:
        """Return one row per line; forget the rows of lines that are gone."""
        kept: dict[tuple, _RenderedRow] = {}
        rows = []
        for line in lines:
            color = speaker_color(line.speaker_id, speaker_ids, source=line.source)
            key = (line, color, layout)
            row = kept.get(key) or self._rows.get(key)
            if row is None:
                row = _RenderedRow(
                    TranscriptLine.row(
                        line.start,
                        line.label,
                        line.text,
                        color=color,
                        source=line.source,
                        layout=layout,
                    )
                )
            kept[key] = row
            rows.append(row)
        self._rows = kept
        return rows
