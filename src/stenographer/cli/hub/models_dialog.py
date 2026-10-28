# SPDX-License-Identifier: GPL-3.0-or-later
"""The Models dialog of the Checks tab: each model present or missing, and its download."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.doctor_view import ModelEntry

log = logging.getLogger(__name__)


class ModelsDialog(Dialog[None]):
    """List the models; ``enter`` downloads the selected missing model after a confirmation."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move(-1)", "Previous model"),
        ("down", "move(1)", "Next model"),
        ("enter", "download", "Download the selected model"),
    ]

    def __init__(
        self,
        model_status: Callable[[], tuple[ModelEntry, ...]],
        model_download: Callable[[str], None],
    ) -> None:
        super().__init__("Models")
        self._model_status = model_status
        self._model_download = model_download
        self.entries: tuple[ModelEntry, ...] = ()
        self.index = 0
        self.status = ""

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="models-list")
        yield Static("", id="models-status", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Close", "cancel"), ("enter", "Download…", "download"))

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.entries = self._model_status()
        self.index = min(self.index, max(0, len(self.entries) - 1))
        rows = tuple(
            (
                f"{entry.label} · {entry.name}",
                StatusToken.text("✓", "present", "ok")
                if entry.present
                else StatusToken.text(DOCTOR_STATE_GLYPHS["fail"], "missing", "danger"),
            )
            for entry in self.entries
        )
        self.query_one("#models-list", SelectableList).set_rows(rows, self.index)
        self.query_one("#models-status", Static).update(self.status)

    def on_row_selected(self, event) -> None:
        event.stop()
        self.index = event.index
        self.reload()

    def action_move(self, offset: int) -> None:
        if self.entries:
            self.index = (self.index + offset) % len(self.entries)
            self.reload()

    def action_download(self) -> None:
        if not self.entries:
            return
        entry = self.entries[self.index]
        if entry.present:
            self.app.notify(f"The {entry.label} is present.")
            return
        log.info(fmt_event("hub", "setup_model_download_prompted", model=entry.model_id))
        self.app.push_screen(
            QuitConfirm(
                f"Download {entry.label} {entry.name} now? ({entry.size})",
                confirm="Download",
            ),
            lambda confirmed: self._confirmed(entry, confirmed),
        )

    def _confirmed(self, entry: ModelEntry, confirmed: bool | None) -> None:
        log.info(
            fmt_event(
                "hub",
                "setup_model_download_confirmed",
                model=entry.model_id,
                confirmed=bool(confirmed),
            )
        )
        if confirmed:
            self.status = f"downloading {entry.label}…"
            self.reload()
            self.run_worker(self._download(entry), group="model-download", exclusive=True)

    async def _download(self, entry: ModelEntry) -> None:
        try:
            await asyncio.to_thread(self._model_download, entry.model_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_model_download_failed", exc, safe=True)
            self.status = f"{DOCTOR_STATE_GLYPHS['fail']} download failed: {exc}"
            self.app.notify(f"Model download failed: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "setup_model_download_completed", model=entry.model_id))
            self.status = f"✓ {entry.label} downloaded"
        self.reload()
