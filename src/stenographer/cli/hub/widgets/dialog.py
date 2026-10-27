# SPDX-License-Identifier: GPL-3.0-or-later
"""The base of each hub dialog: title, body and a row of key buttons."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from stenographer.cli.hub.widgets.button import HubButton


class Dialog[ResultType](ModalScreen[ResultType]):
    """Show a framed dialog; ``escape`` cancels with ``None``.

    Subclasses give ``title``, ``compose_body`` and ``buttons``. Each button is
    ``(key, label, action)``; the action runs on the dialog, so a click and the
    key do the same thing.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    Dialog {
        align: center middle;
        background: transparent;
    }
    Dialog > #dialog-frame {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round #5fd7ff;
        border-title-color: #5fd7ff;
        border-title-style: bold;
        background: transparent;
    }
    Dialog #dialog-body {
        height: auto;
        max-height: 30;
    }
    Dialog #dialog-buttons {
        height: 1;
        margin-top: 1;
        align-horizontal: right;
    }
    """

    def __init__(self, title: str = "") -> None:
        super().__init__()
        self.dialog_title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-frame") as frame:
            frame.border_title = self.dialog_title
            with VerticalScroll(id="dialog-body"):
                yield from self.compose_body()
            with Horizontal(id="dialog-buttons"):
                for key, label, action in self.buttons():
                    yield HubButton(label, key=key, action=action, id=f"dialog-{action}")

    def compose_body(self) -> ComposeResult:
        yield Static("", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Close", "cancel"),)

    def body_widget(self) -> Widget:
        return self.query_one("#dialog-body", VerticalScroll)

    def action_cancel(self) -> None:
        self.dismiss(None)
