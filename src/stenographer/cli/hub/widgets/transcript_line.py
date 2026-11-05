# SPDX-License-Identifier: GPL-3.0-or-later
"""One transcript row: time, speaker and text, in mixed or split layout."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text

from stenographer.cli.hub.widgets.clock import Clock

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
