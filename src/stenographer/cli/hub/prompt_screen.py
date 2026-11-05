# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared layout for focusable hub prompts."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class PromptScreen[Result](ModalScreen[Result]):
    PROMPT_CSS = """
    QuitConfirm, ConfigPrompt {
        align: center middle;
        background: transparent;
    }
    .prompt-dialog {
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: transparent;
    }
    .prompt-message {
        height: auto;
        padding-bottom: 1;
    }
    .prompt-buttons {
        height: 3;
        align-horizontal: right;
    }
    .prompt-buttons Button {
        margin-left: 1;
    }
    """

    def prompt_body(self) -> ComposeResult:
        yield from ()

    def prompt_buttons(self) -> ComposeResult:
        yield from ()

    def compose(self) -> ComposeResult:
        with Vertical(id=self._dialog_id, classes="prompt-dialog"):
            yield Static(self._message, id=self._message_id, classes="prompt-message", markup=False)
            yield from self.prompt_body()
            if self._buttons_id is not None:
                with Horizontal(id=self._buttons_id, classes="prompt-buttons"):
                    yield from self.prompt_buttons()
