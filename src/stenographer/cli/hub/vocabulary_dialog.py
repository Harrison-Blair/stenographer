# SPDX-License-Identifier: GPL-3.0-or-later
"""The list editor of ``refine.vocabulary``: add, edit and delete terms."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Input, Static

from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.lib.config.constants import MAX_VOCABULARY_TERMS
from stenographer.lib.config.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.widgets.row_selected import RowSelected


class VocabularyDialog(Dialog[tuple[str, ...] | None]):
    """Edit a copy of the terms; ``enter`` Done returns them, ``escape`` cancels.

    ``check`` returns the terms as the config reads them or raises
    ``ConfigError``, so the dialog applies the config rules and keeps no copy
    of them. While the term input has focus, letters go to it; ``enter``
    keeps the term and ``escape`` closes the input.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("up", "move(-1)", "Previous term"),
        ("down", "move(1)", "Next term"),
        ("a", "add", "Add a term"),
        ("e", "edit", "Edit the selected term"),
        Binding("delete", "delete", "Delete the selected term", key_display="del"),
        ("enter", "done", "Done"),
    ]
    DEFAULT_CSS = """
    VocabularyDialog #vocab-input {
        display: none;
        margin-top: 1;
    }
    VocabularyDialog #vocab-count {
        margin-top: 1;
        color: #8b93a1;
    }
    """

    def __init__(
        self, terms: tuple[str, ...], check: Callable[[tuple[str, ...]], tuple[str, ...]]
    ) -> None:
        super().__init__("Vocabulary")
        self.terms = list(terms)
        self.check = check
        self.selected = 0
        self.editing: int | None = None

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="vocab-list")
        yield Input(placeholder="term", compact=True, select_on_focus=False, id="vocab-input")
        yield Static("", id="vocab-count", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (
            ("a", "Add", "add"),
            ("e", "Edit", "edit"),
            ("del", "Delete", "delete"),
            ("esc", "Cancel", "cancel"),
            ("enter", "Done", "done"),
        )

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        listing = self.query_one("#vocab-list", SelectableList)
        if self.terms:
            self.selected = max(0, min(self.selected, len(self.terms) - 1))
            listing.set_rows(tuple((term, "") for term in self.terms), self.selected)
        else:
            listing.set_rows((("no terms · a adds one", ""),))
        count = len(self.terms)
        self.query_one("#vocab-count", Static).update(
            f"{count} of {MAX_VOCABULARY_TERMS} terms · spelled exactly as written by refine"
        )

    def _input(self) -> Input:
        return self.query_one("#vocab-input", Input)

    def _open_input(self, value: str, editing: int | None) -> None:
        self.editing = editing
        field = self._input()
        field.value = value
        field.display = True
        field.focus()
        field.cursor_position = len(value)

    def _close_input(self) -> None:
        field = self._input()
        field.display = False
        self.set_focus(None)
        self.editing = None

    def action_add(self) -> None:
        self._open_input("", None)

    def action_edit(self) -> None:
        if self.terms:
            self._open_input(self.terms[self.selected], self.selected)

    def action_delete(self) -> None:
        if self.terms:
            del self.terms[self.selected]
            self._show()

    def action_move(self, offset: int) -> None:
        if self.terms:
            self.selected = (self.selected + offset) % len(self.terms)
            self._show()

    def action_done(self) -> None:
        self.dismiss(tuple(self.terms))

    def action_cancel(self) -> None:
        if self._input().display:
            self._close_input()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        candidate = list(self.terms)
        if self.editing is None:
            candidate.append(event.value)
            index = len(candidate) - 1
        else:
            candidate[self.editing] = event.value
            index = self.editing
        try:
            self.terms = list(self.check(tuple(candidate)))
        except ConfigError as exc:
            self.app.notify(f"Term not kept: {exc.reason}.", severity="error")
            return
        self.selected = index
        self._close_input()
        self._show()

    def on_row_selected(self, event: RowSelected) -> None:
        event.stop()
        if self.terms:
            self.selected = event.index
            self._show()
