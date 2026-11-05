# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirmation prompts used by the hub."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button

from stenographer.cli.hub.prompt_screen import PromptScreen
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.focus_button import FocusButton


class QuitConfirm(PromptScreen[bool]):
    """Ask before the hub stops work and exits."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("y", "confirm", "Confirm"),
        ("q", "confirm_quit", "Confirm"),
        ("ctrl+c", "confirm_quit", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        Binding("question_mark", "app.help", "Help", show=False),
    ]
    CSS = PromptScreen.PROMPT_CSS + "#quit-dialog { width: 64; }"
    _dialog_id = "quit-dialog"
    _message_id = "quit-prompt"
    _buttons_id = "quit-buttons"

    def __init__(
        self,
        message: str,
        *,
        confirm: str = "Confirm",
        cancel: str = "Cancel",
        quit_keys: bool = False,
    ) -> None:
        super().__init__()
        self._message = message
        self._confirm = confirm
        self._cancel = cancel
        self._quit_keys = quit_keys

    def prompt_buttons(self) -> ComposeResult:
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

    def action_confirm_quit(self) -> None:
        if self._quit_keys:
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
