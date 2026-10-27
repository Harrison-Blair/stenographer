# SPDX-License-Identifier: GPL-3.0-or-later
"""The help overlay: one row for each active key binding of the screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.widgets.dialog import Dialog

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import ActiveBinding

_KEY_NAMES = {
    "question_mark": "?",
    "slash": "/",
    "space": "space",
    "delete": "del",
    "pageup": "PgUp",
    "pagedown": "PgDn",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}


class HelpOverlay(Dialog[None]):
    """List the bindings that are active under this overlay; ``?`` closes it."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Close help"),
        ("question_mark", "cancel", "Close help"),
    ]

    def __init__(self, title: str, bindings: dict[str, ActiveBinding]) -> None:
        super().__init__(f"help · {title}")
        self.rows = self.help_rows(bindings)

    @staticmethod
    def help_rows(bindings: dict[str, ActiveBinding]) -> tuple[tuple[str, str], ...]:
        """Return ``(key, description)`` for each shown active binding, in binding order."""
        rows = []
        for key, active in bindings.items():
            binding: Binding = active.binding
            if not binding.show:
                continue
            name = binding.key_display or _KEY_NAMES.get(key, key)
            rows.append((name, binding.description or binding.action))
        return tuple(rows)

    def compose_body(self) -> ComposeResult:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold #5fd7ff", no_wrap=True)
        table.add_column()
        for key, description in self.rows:
            table.add_row(key, Text(description))
        yield Static(table, id="help-rows")

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Close", "cancel"),)
