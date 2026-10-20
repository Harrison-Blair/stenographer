# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker selection and rename dialog for the live app."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from stenographer.cli.live.speaker_select import SpeakerSelect


class RenameDialog(ModalScreen[tuple[str, str] | None]):
    """Choose a system speaker and enter its display name."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    CSS = """
    #rename-dialog {
        width: 56;
        height: auto;
        max-height: 14;
        margin: 1 2;
        padding: 1 2;
        border: round $accent;
        background: transparent;
    }
    #rename-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    def __init__(self, speakers: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self._speakers = speakers

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-dialog"):
            yield Label("Rename system speaker")
            yield SpeakerSelect(
                self._speakers,
                prompt="Choose a speaker",
                id="speaker-select",
            )
            yield Input(placeholder="New speaker name", id="speaker-name")
            with Horizontal(id="rename-actions"):
                yield Button("Rename", variant="primary", id="rename-submit")
                yield Button("Cancel", id="rename-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename-cancel":
            self.dismiss(None)
            return
        speaker_id = self.query_one("#speaker-select", SpeakerSelect).value
        name = self.query_one("#speaker-name", Input).value.strip()
        if not isinstance(speaker_id, str) or not name:
            self.notify("Choose a speaker and enter a name.")
            return
        self.dismiss((speaker_id, name))

    def action_cancel(self) -> None:
        self.dismiss(None)
