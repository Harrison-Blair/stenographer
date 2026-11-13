# SPDX-License-Identifier: GPL-3.0-or-later
"""The Edit title dialog of the Library."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Input

from stenographer.cli.hub.widgets.dialog import Dialog

if TYPE_CHECKING:
    from textual.app import ComposeResult


class TitleDialog(Dialog[str | None]):
    """Edit the title of a session; ``enter`` saves, ``escape`` cancels.

    An empty title removes the title.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("enter", "save", "Save"),
    ]

    def __init__(self, title: str) -> None:
        super().__init__("Edit title")
        self._title = title

    def compose_body(self) -> ComposeResult:
        yield Input(self._title, placeholder="title", id="title-input")

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Save", "save"))

    def on_mount(self) -> None:
        self.query_one("#title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def action_save(self) -> None:
        self.dismiss(self.query_one("#title-input", Input).value)
