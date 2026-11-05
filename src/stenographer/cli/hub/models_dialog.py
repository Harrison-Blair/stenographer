# SPDX-License-Identifier: GPL-3.0-or-later
"""The Models dialog of the Checks tab: each model present or missing, and its download."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS
from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.doctor_view import ModelEntry

log = logging.getLogger(__name__)


class ModelsDialog(Dialog[None]):
    """List the models; ``enter`` downloads the selected missing model."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move(-1)", "Previous model"),
        ("down", "move(1)", "Next model"),
        ("enter", "download", "Download the selected model"),
    ]

    def __init__(
        self,
        model_status: Callable[[], tuple[ModelEntry, ...]],
        model_download: Callable[[str], None],
        download_lock: threading.Lock,
    ) -> None:
        super().__init__("Models")
        self._model_status = model_status
        self._model_download = model_download
        self._download_lock = download_lock
        self.entries: tuple[ModelEntry, ...] = ()
        self.index = 0
        self.status = ""

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="models-list")
        yield Static("", id="models-status", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Close", "cancel"), ("enter", "Download", "download"))

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.entries = self._model_status()
        self._draw()

    def _draw(self) -> None:
        rows = tuple(
            (
                f"{entry.label} · {entry.name} · {entry.size}",
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
        self._draw()

    def action_move(self, offset: int) -> None:
        self.index = (self.index + offset) % len(self.entries)
        self._draw()

    def action_download(self) -> None:
        self.reload()
        entry = self.entries[self.index]
        if entry.present:
            self.app.notify(f"The {entry.label} is present.")
            return
        self.run_worker(self._download(entry), group="model-download")

    def _download_and_release(self, model_id: str) -> None:
        try:
            self._model_download(model_id)
        finally:
            self._download_lock.release()

    async def _download(self, entry: ModelEntry) -> None:
        # The lock outlives this dialog: closing it ends this worker, not the download thread.
        if not self._download_lock.acquire(blocking=False):
            self.app.notify("A model download is running.", severity="warning")
            return
        log.info(fmt_event("hub", "setup_model_download_started", model=entry.model_id))
        self.status = f"downloading {entry.label}…"
        self.reload()
        try:
            await asyncio.to_thread(self._download_and_release, entry.model_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_model_download_failed", exc, safe=True)
            self.status = f"{DOCTOR_STATE_GLYPHS['fail']} download failed: {exc}"
            self.app.notify(f"Model download failed: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "setup_model_download_completed", model=entry.model_id))
            self.status = f"✓ {entry.label} downloaded"
        self.reload()
