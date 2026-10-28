# SPDX-License-Identifier: GPL-3.0-or-later
"""The input device dialog of the Record screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding

from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected


class DeviceDialog(Dialog[tuple[str | None, str | None] | None]):
    """List the input devices; return ``(value, label)``, or ``(None, None)`` for the setting."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("enter", "choose", "Use device"),
        ("up", "move(-1)", "Previous device"),
        ("down", "move(1)", "Next device"),
    ]

    def __init__(
        self, devices: list[tuple[str, str]], *, setting: str, current: str | None
    ) -> None:
        super().__init__("Input device")
        self.choices: tuple[tuple[str | None, str | None], ...] = ((None, None), *devices)
        self._setting = setting
        self.selected = next(
            (index for index, (value, _label) in enumerate(self.choices) if value == current), 0
        )

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="device-list")

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Use device", "choose"))

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        rows = tuple(
            (label or f"Settings default · {self._setting}", "") for _value, label in self.choices
        )
        self.query_one("#device-list", SelectableList).set_rows(rows, self.selected)

    def action_move(self, offset: int) -> None:
        self.selected = max(0, min(len(self.choices) - 1, self.selected + offset))
        self._show()

    def on_row_selected(self, event: RowSelected) -> None:
        event.stop()
        self.selected = event.index

    def action_choose(self) -> None:
        self.dismiss(self.choices[self.selected])
