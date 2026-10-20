# SPDX-License-Identifier: GPL-3.0-or-later
"""Text prompts for configuration edits, searches, and unsaved changes."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class ConfigPrompt(ModalScreen[str | None]):
    """Show a text input or a save/discard prompt and return its choice."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    CSS = """
    ConfigPrompt {
        align: center middle;
        background: $background 75%;
    }
    #config-prompt {
        width: 72;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #config-prompt-message {
        height: auto;
        padding-bottom: 1;
    }
    #config-prompt-buttons {
        height: 3;
        align-horizontal: right;
    }
    #config-prompt-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        message: str,
        *,
        initial: str | None = None,
        choices: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__()
        self._message = message
        self._initial = initial
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="config-prompt"):
            yield Static(self._message, id="config-prompt-message", markup=False)
            if self._initial is not None:
                yield Input(self._initial, id="config-prompt-input")
            if self._choices:
                with Horizontal(id="config-prompt-buttons"):
                    for label, value in self._choices:
                        yield Button(label, id=f"choice-{value}")

    def on_mount(self) -> None:
        if self._initial is not None:
            field = self.query_one("#config-prompt-input", Input)
            field.focus()
            field.cursor_position = len(field.value)
        elif self._choices:
            self.query_one("#choice-stay", Button).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        value = event.button.id.removeprefix("choice-")
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
