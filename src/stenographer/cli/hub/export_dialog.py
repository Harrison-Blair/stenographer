# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export dialog of the Library: a format and an output folder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label, Static

from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.dialog import Dialog

FORMATS = ("md", "jsonl", "srt", "txt")


class ExportDialog(Dialog[None]):
    """Choose ``md``, ``jsonl``, ``srt`` or ``txt`` and a folder; ``enter`` exports."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("enter", "export", "Export"),
        Binding("tab", "next_format", "Next format", priority=True),
    ]
    DEFAULT_CSS = """
    ExportDialog .export-row {
        height: auto;
        margin-bottom: 1;
    }
    ExportDialog .export-row Label {
        width: 10;
        padding: 0 0 0 2;
    }
    ExportDialog #export-folder-row Label {
        padding: 1 0 0 2;
    }
    ExportDialog .export-row Input {
        width: 1fr;
    }
    ExportDialog #export-format-hint {
        color: #8b93a1;
        padding: 0 0 0 12;
        margin-bottom: 1;
    }
    ExportDialog #export-format-row {
        margin-bottom: 0;
    }
    """

    def __init__(self, session_id: str, export: Callable[[str, Path], Awaitable[Path]]) -> None:
        super().__init__(f"Export {session_id}")
        self.export_format = FORMATS[0]
        self._export = export
        self._exporting = False

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="export-row", id="export-format-row"):
            yield Label("Format")
            for name in FORMATS:
                button = HubButton(
                    self._format_label(name),
                    action=f"choose_format('{name}')",
                    tight=True,
                    id=f"export-format-{name}",
                )
                # Inline: the app rules of HubButton outrank dialog CSS. Tight buttons with
                # a gap of 2 keep the row inside a dialog of 60 columns.
                button.styles.margin = (0, 2, 0, 0)
                yield button
        yield Label("tab next format", id="export-format-hint")
        with Horizontal(classes="export-row", id="export-folder-row"):
            yield Label("Folder")
            yield Input("~/Documents", placeholder="Output folder", id="export-folder")

        yield Static("", id="export-error", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Cancel", "cancel"), ("enter", "Export", "export"))

    def on_mount(self) -> None:
        self.query_one("#export-folder", Input).focus()

    def _format_label(self, name: str) -> str:
        return f"({'●' if name == self.export_format else ' '}) {name}"

    def action_choose_format(self, name: str) -> None:
        self.export_format = name
        for option in FORMATS:
            self.query_one(f"#export-format-{option}", HubButton).set_label(
                self._format_label(option)
            )

    def action_next_format(self) -> None:
        index = FORMATS.index(self.export_format)
        self.action_choose_format(FORMATS[(index + 1) % len(FORMATS)])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_export()

    def action_export(self) -> None:
        folder = self.query_one("#export-folder", Input).value.strip()
        if not folder:
            self.notify("Enter an output folder.")
            return
        if self._exporting:
            return
        self._exporting = True
        self.query_one("#export-error", Static).update("")
        self.run_worker(self._run_export(self.export_format, Path(folder).expanduser()))

    async def _run_export(self, format_name: str, folder: Path) -> None:
        try:
            path = await self._export(format_name, folder)
        except Exception as exc:
            self.query_one("#export-error", Static).update(f"Could not export this session: {exc}")
            self._exporting = False
        else:
            self.dismiss(None)
            self.app.notify(f"Exported to {path}")
