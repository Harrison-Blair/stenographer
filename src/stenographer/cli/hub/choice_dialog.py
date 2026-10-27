# SPDX-License-Identifier: GPL-3.0-or-later
"""The list of allowed values of one choice or device setting."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding

from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected


class ChoiceDialog(Dialog[int | None]):
    """Show the options with ``▶`` on the current one; return the chosen index."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("up", "move(-1)", "Previous option"),
        ("down", "move(1)", "Next option"),
        ("enter", "choose", "Choose the option"),
    ]

    def __init__(self, title: str, options: tuple[str, ...], selected: int) -> None:
        super().__init__(title)
        self.options = options
        self.selected = selected

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="choice-list")

    def on_mount(self) -> None:
        self._show()

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Choose", "choose"))

    def _show(self) -> None:
        rows = tuple((option, "") for option in self.options)
        self.query_one("#choice-list", SelectableList).set_rows(rows, self.selected)

    def action_move(self, offset: int) -> None:
        self.selected = (self.selected + offset) % len(self.options)
        self._show()

    def action_choose(self) -> None:
        self.dismiss(self.selected)

    def on_row_selected(self, event: RowSelected) -> None:
        event.stop()
        self.dismiss(event.index)
