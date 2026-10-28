# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirmation prompts used by the hub."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.focus_button import FocusButton


class QuitConfirm(ModalScreen[bool]):
    """Ask before the hub stops work and exits."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("y", "confirm", "Confirm"),
        ("q", "confirm", "Confirm"),
        ("ctrl+c", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        Binding("question_mark", "app.help", "Help", show=False),
    ]
    CSS = """
    QuitConfirm {
        align: center middle;
        background: transparent;
    }
    #quit-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: transparent;
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

    def __init__(self, message: str, *, confirm: str = "Confirm", cancel: str = "Cancel") -> None:
        super().__init__()
        self._message = message
        self._confirm = confirm
        self._cancel = cancel

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-dialog"):
            yield Static(self._message, id="quit-prompt", markup=False)
            with Horizontal(id="quit-buttons"):
                yield FocusButton(HubButton.label_text(self._cancel, "n"), id="cancel-quit")
                yield FocusButton(
                    HubButton.label_text(self._confirm, "y"), id="confirm-quit", variant="error"
                )

    def on_mount(self) -> None:
        self.query_one("#cancel-quit", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-quit")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
