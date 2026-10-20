# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual shell for the stenographer hub."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
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
        ("left", "previous_config_group", "Previous config group"),
        ("right", "next_config_group", "Next config group"),
        ("up", "previous_config_key", "Previous config key"),
        ("down", "next_config_key", "Next config key"),
        ("enter", "edit_config", "Edit config key"),
        ("u", "undo_config", "Undo config change"),
        ("shift+d", "reset_config", "Reset config key"),
        ("/", "search_config", "Search config keys"),
        ("ctrl+s", "save_config", "Save config"),
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

    def __init__(
        self,
        services,
        *,
        config_editor: ConfigEditor | None = None,
        config_path: pathlib.Path | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.config_editor = config_editor or (
            ConfigEditor(config_path) if config_path is not None else None
        )
        self._section = "live"
        self._pending_section: str | None = None
        self._pending_quit = False

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
        if self.config_editor is not None and self.config_editor.read_only:
            self.notify(
                "Invalid configuration. Select Config to view the error and fix "
                f"{self.config_editor.path}.",
                severity="error",
            )
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
        if self._section == "config" and self.config_editor is not None:
            content = self.config_editor.render()
        section_view.border_title = title
        section_view.update(content)
        hints = self.query_one("#key-hints", Static)
        if self._section == "config":
            hints.update(
                "enter edit   u undo   D reset   / search   ctrl+s save   ←/→ group   ↑/↓ key"
            )
        else:
            hints.update("space start recording   1-6 sections   q quit")

    def action_previous_config_group(self) -> None:
        self._move_config_group(-1)

    def action_next_config_group(self) -> None:
        self._move_config_group(1)

    def action_previous_config_key(self) -> None:
        self._move_config_key(-1)

    def action_next_config_key(self) -> None:
        self._move_config_key(1)

    def _move_config_group(self, offset: int) -> None:
        if self._section == "config" and self.config_editor is not None:
            self.config_editor.move_group(offset)
            self._refresh_view()

    def _move_config_key(self, offset: int) -> None:
        if self._section == "config" and self.config_editor is not None:
            self.config_editor.move_key(offset)
            self._refresh_view()

    def action_edit_config(self) -> None:
        editor = self.config_editor
        if self._section != "config" or editor is None:
            return
        key = editor.selected_key
        if key is None or editor.read_only:
            return
        value = editor.value(key)
        if value is None:
            initial = ""
        elif isinstance(value, tuple):
            initial = ", ".join(map(str, value))
        else:
            initial = str(value)
        self.push_screen(
            ConfigPrompt(f"Edit {key}", initial=initial),
            lambda result: self._apply_config_edit(key, result),
        )

    def _apply_config_edit(self, key: str, value: str | None) -> None:
        if value is None:
            return
        if self.config_editor is None:
            return
        try:
            self.config_editor.edit(key, value)
        except (ValueError, TypeError, ConfigError) as exc:
            self.notify(str(exc), severity="error")
        self._refresh_view()

    def action_undo_config(self) -> None:
        editor = self.config_editor
        if self._section == "config" and editor is not None and editor.undo():
            self._refresh_view()

    def action_reset_config(self) -> None:
        editor = self.config_editor
        if self._section != "config" or editor is None:
            return
        key = editor.selected_key
        if key is not None and not editor.read_only:
            try:
                editor.reset(key)
            except (ValueError, TypeError, ConfigError) as exc:
                self.notify(str(exc), severity="error")
            self._refresh_view()

    def action_search_config(self) -> None:
        editor = self.config_editor
        if self._section != "config" or editor is None:
            return
        if editor.read_only:
            return
        self.push_screen(
            ConfigPrompt("Search configuration keys", initial=""),
            self._search_config,
        )

    def _search_config(self, term: str | None) -> None:
        if self.config_editor is None:
            return
        if term is not None and not self.config_editor.search(term):
            self.notify(f"No configuration keys match {term!r}.", severity="warning")
        self._refresh_view()

    def action_save_config(self) -> None:
        if self._section == "config":
            self._save_config()

    def _save_config(self) -> bool:
        editor = self.config_editor
        if editor is None or editor.read_only:
            return False
        try:
            result = editor.save()
        except (ConfigError, ConfigPersistenceError) as exc:
            self.notify(str(exc), severity="error")
            self._refresh_view()
            return False
        if result.changed:
            update_config = getattr(self.services, "update_config", None)
            if update_config is not None:
                update_config(editor.config)
            message = f"Saved {result.path}"
            if result.backup_path is not None:
                message += f"; backup: {result.backup_path}"
            self.notify(message)
        else:
            self.notify("Configuration is unchanged.")
        self._refresh_view()
        return True

    def _select_section(self, section: str) -> None:
        if (
            self._section == "config"
            and section != "config"
            and self.config_editor is not None
            and self.config_editor.dirty
        ):
            self._pending_section = section
            self.push_screen(
                ConfigPrompt(
                    "Save or discard unsaved configuration changes?",
                    choices=(("Save", "save"), ("Discard", "discard"), ("Stay", "stay")),
                ),
                self._resolve_config_navigation,
            )
            return
        self._show_section(section)

    def _resolve_config_navigation(self, choice: str | None) -> None:
        section = self._pending_section
        quitting = self._pending_quit
        self._pending_section = None
        self._pending_quit = False
        if choice in {None, "stay"}:
            return
        if choice == "save" and not self._save_config():
            return
        if choice == "discard" and self.config_editor is not None:
            self.config_editor.discard()
        if quitting:
            self.action_request_quit()
        elif section is not None:
            self._show_section(section)

    def _show_section(self, section: str) -> None:
        self._section = section
        self._refresh_view()
        log.info(fmt_event("hub", "section_changed", section=section))

    async def action_start_recording(self) -> None:
        if self._section != "live" or self.services.recording:
            return
        if self.config_editor is not None and self.config_editor.read_only:
            self.notify("Fix the invalid configuration before recording.", severity="error")
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
        if (
            self._section == "config"
            and self.config_editor is not None
            and self.config_editor.dirty
        ):
            self._pending_quit = True
            self.push_screen(
                ConfigPrompt(
                    "Save or discard unsaved configuration changes?",
                    choices=(("Save", "save"), ("Discard", "discard"), ("Stay", "stay")),
                ),
                self._resolve_config_navigation,
            )
            return
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
