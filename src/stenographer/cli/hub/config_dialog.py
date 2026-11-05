# SPDX-License-Identifier: GPL-3.0-or-later
"""Text prompts for configuration edits, searches, and unsaved changes."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Input

from stenographer.cli.hub.prompt_screen import PromptScreen
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.focus_button import FocusButton


class ConfigPrompt(PromptScreen[str | None]):
    """Show a text input or a save/discard prompt and return its choice.

    Each choice button prints its key; ``escape`` stays (it returns ``None``).
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("s", "choose('save')", "Save"),
        ("d", "choose('discard')", "Discard"),
        Binding("question_mark", "app.help", "Help", show=False),
    ]
    CHOICE_KEYS: ClassVar[dict[str, str]] = {"save": "s", "discard": "d", "stay": "esc"}
    CSS = PromptScreen.PROMPT_CSS + "#config-prompt { width: 72; }"
    _dialog_id = "config-prompt"
    _message_id = "config-prompt-message"

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
        self._buttons_id = "config-prompt-buttons" if choices else None

    def prompt_body(self) -> ComposeResult:
        if self._initial is not None:
            yield Input(self._initial, id="config-prompt-input")

    def prompt_buttons(self) -> ComposeResult:
        for label, value in self._choices:
            yield FocusButton(
                HubButton.label_text(label, self.CHOICE_KEYS.get(value)),
                id=f"choice-{value}",
            )

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "choose":
            return any(value == parameters[0] for _label, value in self._choices)
        return True

    def action_choose(self, value: str) -> None:
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
