# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual shell for the stenographer hub."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.lib.logging.pipeline import fmt_event, log_failure

log = logging.getLogger(__name__)

_SECTIONS = (
    ("live", "Live"),
    ("files", "Files"),
    ("sessions", "Sessions"),
    ("config", "Config"),
    ("setup", "Setup"),
    ("doctor", "Doctor"),
)
_PLACEHOLDERS = {
    "live": "Press space to start recording.",
    "files": "File transcription will appear here.",
    "sessions": "Saved sessions will appear here.",
    "config": "Configuration settings will appear here.",
    "setup": "Setup steps will appear here.",
    "doctor": "System checks will appear here.",
}


class HubApp(App[None]):
    """Show six sections while shared work continues in the service owner."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("1", "show_live", "Live"),
        ("2", "show_files", "Files"),
        ("3", "show_sessions", "Sessions"),
        ("4", "show_config", "Config"),
        ("5", "show_setup", "Setup"),
        ("6", "show_doctor", "Doctor"),
        ("space", "start_recording", "Start recording"),
        ("q", "request_quit", "Quit"),
        ("ctrl+c", "request_quit", "Quit"),
    ]
    CSS = """
    Screen {
        background: #0b0d12;
        color: #e3e6ec;
    }
    #hub-layout {
        height: 1fr;
        padding: 1;
    }
    #sidebar {
        width: 25;
        height: 1fr;
        margin-right: 1;
        padding: 1 2;
        border: round #3a4150;
    }
    #section-content {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        border: round #3a4150;
    }
    #key-hints {
        height: 1;
        padding: 0 2;
        color: #a0a8b8;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self.services = services
        self._section = "live"

    @property
    def current_section(self) -> str:
        return self._section

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-layout"):
            yield Static("", id="sidebar", markup=False)
            yield Static("", id="section-content", markup=False)
        yield Static(
            "space start recording   1-6 sections   q quit",
            id="key-hints",
            markup=False,
        )

    def on_mount(self) -> None:
        self.query_one("#sidebar", Static).border_title = "stenographer"
        self._refresh_view()
        log.info(fmt_event("hub", "started"))

    def action_show_live(self) -> None:
        self._select_section("live")

    def action_show_files(self) -> None:
        self._select_section("files")

    def action_show_sessions(self) -> None:
        self._select_section("sessions")

    def action_show_config(self) -> None:
        self._select_section("config")

    def action_show_setup(self) -> None:
        self._select_section("setup")

    def action_show_doctor(self) -> None:
        self._select_section("doctor")

    def _select_section(self, section: str) -> None:
        self._section = section
        self._refresh_view()
        log.info(fmt_event("hub", "section_changed", section=section))

    def _refresh_view(self) -> None:
        rows = []
        for index, (section, label) in enumerate(_SECTIONS, start=1):
            marker = ">" if section == self._section else " "
            badge = "0" if section == "doctor" else ""
            rows.append(f"{marker} {index} {label:<8} {badge}")
        self.query_one("#sidebar", Static).update("\n".join(rows))

        title = next(label for section, label in _SECTIONS if section == self._section)
        content = _PLACEHOLDERS[self._section]
        if self._section == "live" and self.services.recording:
            content = "Recording is active. Change sections without stopping it."
        elif self._section == "files" and self.services.files_running:
            content = "A Files job is running. Change sections without cancelling it."
        section_view = self.query_one("#section-content", Static)
        section_view.border_title = title
        section_view.update(content)

    async def action_start_recording(self) -> None:
        if self._section != "live" or self.services.recording:
            return
        try:
            await asyncio.to_thread(self.services.start_recording)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_start_failed", exc, safe=True)
            self.notify(f"Could not start recording: {exc}", severity="error")
            return
        log.info(fmt_event("hub", "recording_started"))
        self._refresh_view()

    def action_request_quit(self) -> None:
        if self.services.recording:
            log.info(fmt_event("hub", "quit_prompted", work="recording"))
            self.push_screen(
                QuitConfirm("Stop recording and save the session before quitting?"),
                self._confirm_recording_quit,
            )
        elif self.services.files_running:
            self._prompt_files_quit()
        else:
            self.exit()

    async def _confirm_recording_quit(self, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "quit_confirmed", work="recording", confirmed=bool(confirmed)))
        if not confirmed:
            return
        try:
            await asyncio.to_thread(self.services.stop_recording)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_stop_failed", exc, safe=True)
            self.notify(f"Could not save the recording: {exc}", severity="error")
            return
        self._refresh_view()
        if self.services.files_running:
            self._prompt_files_quit()
        else:
            self.exit()

    def _prompt_files_quit(self) -> None:
        log.info(fmt_event("hub", "quit_prompted", work="files"))
        self.push_screen(
            QuitConfirm("Cancel the running Files job before quitting?"),
            self._confirm_files_quit,
        )

    async def _confirm_files_quit(self, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "quit_confirmed", work="files", confirmed=bool(confirmed)))
        if not confirmed:
            return
        try:
            await asyncio.to_thread(self.services.cancel_files)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: files_cancel_failed", exc, safe=True)
            self.notify(f"Could not cancel the Files job: {exc}", severity="error")
            return
        self.exit()
