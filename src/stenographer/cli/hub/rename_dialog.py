# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rename speaker dialog of the hub."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label

from stenographer.cli.hub.speaker_select import SpeakerSelect
from stenographer.cli.hub.widgets.dialog import Dialog


class RenameDialog(Dialog[tuple[str, str] | None]):
    """Choose a speaker and enter its new name; ``enter`` renames, ``escape`` cancels."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("enter", "rename", "Rename"),
    ]
    DEFAULT_CSS = """
    RenameDialog .rename-row {
        height: auto;
        margin-bottom: 1;
    }
    RenameDialog .rename-row Label {
        width: 14;
        padding: 0 0 0 2;
    }
    RenameDialog .rename-row SpeakerSelect, RenameDialog .rename-row Input {
        width: 1fr;
    }
    """

    def __init__(self, speakers: tuple[tuple[str, str], ...]) -> None:
        super().__init__("Rename speaker")
        self._speakers = speakers

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="rename-row"):
            yield Label("Speaker")
            yield SpeakerSelect(
                self._speakers,
                prompt="Choose a speaker",
                value=self._speakers[0][0] if self._speakers else SpeakerSelect.BLANK,
                compact=True,
                id="speaker-select",
            )
        with Horizontal(classes="rename-row"):
            yield Label("New name")
            yield Input(placeholder="New speaker name", compact=True, id="speaker-name")

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Rename", "rename"))

    def on_mount(self) -> None:
        self.query_one("#speaker-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_rename()

    def action_rename(self) -> None:
        speaker_id = self.query_one("#speaker-select", SpeakerSelect).value
        name = self.query_one("#speaker-name", Input).value.strip()
        if not isinstance(speaker_id, str) or not name:
            self.notify("Choose a speaker and enter a name.")
            return
        self.dismiss((speaker_id, name))
