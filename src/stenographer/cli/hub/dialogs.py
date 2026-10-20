# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirmation prompts used by the hub."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class QuitConfirm(ModalScreen[bool]):
    """Ask before the hub stops work and exits."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("y", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]
    CSS = """
    QuitConfirm {
        align: center middle;
        background: $background 75%;
    }
    #quit-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #quit-prompt {
        height: auto;
        padding-bottom: 1;
    }
    #quit-buttons {
        height: 3;
        align-horizontal: right;
    }
    #quit-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-dialog"):
            yield Static(self._message, id="quit-prompt", markup=False)
            with Horizontal(id="quit-buttons"):
                yield Button("Confirm", id="confirm-quit", variant="error")
                yield Button("Cancel", id="cancel-quit")

    def on_mount(self) -> None:
        self.query_one("#cancel-quit", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-quit")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
