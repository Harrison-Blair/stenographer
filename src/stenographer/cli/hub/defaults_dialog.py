# SPDX-License-Identifier: GPL-3.0-or-later
"""The Defaults dialog of the Checks tab: confirm before writing the default config."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.widgets.dialog import Dialog

if TYPE_CHECKING:
    import pathlib

    from textual.app import ComposeResult


class DefaultsDialog(Dialog[bool]):
    """Ask before the default configuration replaces the file; ``y`` confirms."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("y", "confirm", "Write the default configuration"),
    ]

    def __init__(self, path: pathlib.Path, unsaved_count: int = 0) -> None:
        super().__init__("Write the default configuration?")
        self.path = path
        self.unsaved_count = unsaved_count

    def compose_body(self) -> ComposeResult:
        yield Static(
            f"Write the default configuration to {self.path}.\n"
            "The current file is kept as a timestamped backup "
            f"({self.path.name}.bak-<time>)."
            + (
                f"\n{self.unsaved_count} unsaved change(s) will be discarded."
                if self.unsaved_count
                else ""
            ),
            id="defaults-message",
            markup=False,
        )

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("y", "Write defaults", "confirm"))

    def action_confirm(self) -> None:
        self.dismiss(True)
