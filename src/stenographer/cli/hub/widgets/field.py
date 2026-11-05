# SPDX-License-Identifier: GPL-3.0-or-later
"""One settings row: dot slot, label, control, and an optional note beside it."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

_ACCENT_BOLD = "bold #5fd7ff"


class Field(Static):
    """Show a settings row; ``▶`` marks the focused row and ``●`` an unsaved change.

    Every label reserves the two-character slot of both marks, so labels align
    whether or not a row is focused or changed. The control takes the rest of the row;
    a note (a default, an error or the editing state) takes a column of its own.
    """

    DEFAULT_CSS = """
    Field {
        height: auto;
    }
    """
    LABEL_WIDTH = 20
    CONTROL_WIDTH = 30

    def __init__(
        self,
        label: str,
        control: str | Text,
        note: str = "",
        *,
        changed: bool = False,
        focused: bool = False,
        **kwargs,
    ) -> None:
        super().__init__("", markup=False, **kwargs)
        self.label = label
        self.note = note
        self.set_value(control, changed=changed, focused=focused)

    def set_value(self, control: str | Text, *, changed: bool, focused: bool = False) -> None:
        self.control = control
        self.changed = changed
        self.focused = focused
        self.update(self.row())

    def row(self) -> Table:
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=2, no_wrap=True)
        table.add_column(width=self.LABEL_WIDTH, no_wrap=True, overflow="ellipsis")
        if self.note:
            table.add_column(width=self.CONTROL_WIDTH, overflow="fold")
            table.add_column(ratio=1)
        else:
            table.add_column(ratio=1, overflow="fold")
        style = _ACCENT_BOLD if self.focused else None
        cells = (
            Text.assemble(
                ("▶" if self.focused else " ", _ACCENT_BOLD),
                ("●" if self.changed else " ", "#ffaf5f"),
            ),
            Text(self.label, style=style),
            self.control if isinstance(self.control, Text) else Text(self.control, style=style),
        )
        table.add_row(*cells, *((Text(self.note, style="#8b93a1"),) if self.note else ()))
        return table
