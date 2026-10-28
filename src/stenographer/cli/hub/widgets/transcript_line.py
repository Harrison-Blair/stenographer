# SPDX-License-Identifier: GPL-3.0-or-later
"""One transcript row: time, speaker and text, in mixed or split layout."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

_DIM = "#8b93a1"


class TranscriptLine(Static):
    """Show one final, pending or marker line; text wraps under its own column."""

    DEFAULT_CSS = """
    TranscriptLine {
        height: auto;
    }
    """

    def __init__(
        self,
        start: float | None,
        label: str,
        text: str,
        *,
        color: str = "default",
        source: str = "mic",
        layout: str = "mixed",
        state: str = "final",
        **kwargs,
    ) -> None:
        super().__init__("", markup=False, **kwargs)
        self.start = start
        self.speaker = label
        self.line_text = text
        self.color = color
        self.source = source
        self.line_layout = layout
        self.state = state
        self.update(self.row())

    def row(self) -> Table | Text:
        if self.state == "marker":
            return Text(f"── {self.line_text} ──", style=_DIM, no_wrap=True)
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=8, no_wrap=True)
        time = Text(self.clock(self.start), style=_DIM)
        who_style = _DIM if self.state == "pending" else f"bold {self.color}"
        text_style = _DIM if self.state == "pending" else None
        body = self.line_text.replace("\n", " ")
        if self.line_layout == "split":
            table.add_column(ratio=1)
            table.add_column(ratio=1)
            cell = Text()
            cell.append(self.speaker, style=who_style)
            cell.append(f"  {body}", style=text_style)
            dot = Text("·", style=_DIM)
            mic, system = (cell, dot) if self.source == "mic" else (dot, cell)
            table.add_row(time, mic, system)
        else:
            table.add_column(width=10, no_wrap=True, overflow="ellipsis")
            table.add_column(ratio=1)
            table.add_row(time, Text(self.speaker, style=who_style), Text(body, style=text_style))
        return table

    @staticmethod
    def clock(seconds: float | None) -> str:
        if seconds is None:
            return ""
        whole = max(0, int(seconds))
        hours, remainder = divmod(whole, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
