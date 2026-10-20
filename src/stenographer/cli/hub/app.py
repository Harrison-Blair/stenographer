# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual shell for the stenographer hub."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from collections.abc import Callable
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, build_report
from stenographer.cli.hub.sessions_view import SessionsPanel
from stenographer.cli.hub.setup_state import SetupWizard
from stenographer.cli.hub.setup_wizard import render as render_setup
from stenographer.cli.hub.setup_wizard import test_step as test_setup_step
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
from stenographer.lib.config.models import Config
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
        ("enter", "edit_config", "Edit config key or show doctor details"),
        ("b", "setup_back", "Previous setup step"),
        ("s", "setup_skip", "Skip setup step"),
        ("t", "session_retranscribe", "Re-transcribe session or test setup step"),
        ("e", "setup_edit", "Edit setup value"),
        ("shift+q", "setup_quick", "Quick setup"),
        ("m", "setup_download_model", "Download ASR model"),
        ("r", "session_rename", "Rename speaker or re-check doctor"),
        ("p", "session_playback", "Play or stop session"),
        ("d", "session_rediarize", "Re-diarize session"),
        ("x", "session_export", "Export session"),
        ("delete", "session_delete", "Delete session"),
        ("f", "doctor_fix", "Fix in Setup"),
        ("l", "doctor_open_log", "Open log"),
        ("c", "doctor_copy_report", "Copy doctor report"),
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
        setup_test: Callable[[str, Config], str] | None = None,
        model_download: Callable[[str], None] | None = None,
        doctor_probe: Callable[[Config, pathlib.Path | None], DoctorReport] | None = None,
        open_log: Callable[[], bool] | None = None,
        copy_report: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.sessions_panel = SessionsPanel(
            getattr(services, "session_store", None), id="sessions-panel"
        )
        self._session_job_status: str | None = None
        self._pending_speaker_id: str | None = None
        self._pending_delete_session: str | None = None
        self.config_editor = config_editor or (
            ConfigEditor(config_path) if config_path is not None else None
        )
        self._section = "live"
        self._pending_section: str | None = None
        self._pending_quit = False
        self.setup_wizard = SetupWizard()
        self._setup_test = setup_test or self._default_setup_test
        if model_download is None:
            from stenographer.lib.transcribe.download import download_model

            model_download = download_model
        self._model_download = model_download
        self._doctor_probe = doctor_probe or build_report
        if open_log is None:
            from stenographer.cli.hub.doctor_view import default_log_opener

            open_log = default_log_opener
        self._open_log = open_log
        self._copy_report = copy_report
        self._doctor_report: DoctorReport | None = None
        self._doctor_loading = False
        self._doctor_index = 0
        self._doctor_details = False
        self._pending_model: str | None = None

    @property
    def current_section(self) -> str:
        return self._section

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-layout"):
            yield Static("", id="sidebar", markup=False)
            yield Static("", id="section-content", markup=False)
            yield self.sessions_panel
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
        if self.config_editor is not None:
            self._request_doctor_check()
        log.info(fmt_event("hub", "started"))

    def on_unmount(self) -> None:
        stop_playback = getattr(self.services, "stop_session_playback", None)
        if stop_playback is not None:
            try:
                stop_playback()
            except Exception as exc:
                log_failure(
                    log, logging.ERROR, "hub: session_playback_cleanup_failed", exc, safe=False
                )

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
            if section == "doctor":
                badge = (
                    f"{self._doctor_report.warn_count}W {self._doctor_report.fail_count}F"
                    if self._doctor_report is not None
                    else "..."
                    if self._doctor_loading
                    else "0W 0F"
                )
            else:
                badge = ""
            rows.append(f"{marker} {index} {label:<8} {badge}")
        self.query_one("#sidebar", Static).update("\n".join(rows))

        title = next(label for section, label in _SECTIONS if section == self._section)
        content = _PLACEHOLDERS[self._section]
        if self._section == "live" and self.services.recording:
            content = "Recording is active. Change sections without stopping it."
        elif self._section == "files" and self.services.files_running:
            content = "A Files job is running. Change sections without cancelling it."
        elif self._section == "setup":
            config = self._current_config()
            content = render_setup(self.setup_wizard, config)
        elif self._section == "doctor":
            if self._doctor_report is None:
                content = (
                    "Checking system capabilities…"
                    if self._doctor_loading
                    else "Press r to check system capabilities."
                )
            else:
                content = self._doctor_report.render(
                    selected_index=self._doctor_index,
                    details=self._doctor_details,
                )
        section_view = self.query_one("#section-content", Static)
        section_view.display = self._section != "sessions"
        self.sessions_panel.display = self._section == "sessions"
        self.sessions_panel.set_job_status(self._session_job_status)
        if self._section == "config" and self.config_editor is not None:
            content = self.config_editor.render()
        section_view.border_title = title
        section_view.update(content)
        hints = self.query_one("#key-hints", Static)
        if self._section == "config":
            hints.update(
                "enter edit   u undo   D reset   / search   ctrl+s save   ←/→ group   ↑/↓ key"
            )
        elif self._section == "setup":
            hints.update("enter next   b back   s skip   t test   e edit   D defaults   Q quick")
        elif self._section == "doctor":
            hints.update("r re-check   enter details   f fix in Setup   l open log   c copy report")
        elif self._section == "sessions":
            hints.update(
                "↑/↓ session   p play   d re-diarize   t re-transcribe   "
                "r rename   x export   del delete"
            )
        else:
            hints.update("space start recording   1-6 sections   q quit")

    def action_previous_config_group(self) -> None:
        self._move_config_group(-1)

    def action_next_config_group(self) -> None:
        self._move_config_group(1)

    def action_previous_config_key(self) -> None:
        if self._section == "sessions":
            self._move_session_selection(-1)
        elif self._section == "doctor":
            self._move_doctor_check(-1)
        else:
            self._move_config_key(-1)

    def action_next_config_key(self) -> None:
        if self._section == "sessions":
            self._move_session_selection(1)
        elif self._section == "doctor":
            self._move_doctor_check(1)
        else:
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
        if self._section == "doctor":
            self._doctor_details = not self._doctor_details
            log.info(fmt_event("hub", "doctor_details_toggled", expanded=self._doctor_details))
            self._refresh_view()
            return
        if self._section == "setup":
            self.action_setup_next()
            return
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
        if self._section == "setup":
            log.info(fmt_event("hub", "setup_defaults_requested"))
            self.run_worker(self._write_setup_defaults(), group="setup", exclusive=True)
            return
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
        if self._section in {"config", "setup"}:
            if self._section == "setup":
                log.info(fmt_event("hub", "setup_config_save_requested"))
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
            self._section in {"config", "setup"}
            and section not in {"config", "setup"}
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
        if section == "doctor" and self._doctor_report is None and not self._doctor_loading:
            self._request_doctor_check()
        log.info(fmt_event("hub", "section_changed", section=section))
        if section == "sessions":
            self._load_sessions()

    def _load_sessions(self) -> None:
        self.sessions_panel.set_loading(True)
        self._refresh_view()
        self.run_worker(self._read_sessions(), group="sessions-list", exclusive=True)

    async def _read_sessions(self) -> None:
        store = self.sessions_panel.store
        if store is None:
            self.sessions_panel.set_summaries(())
        else:
            try:
                summaries = await asyncio.to_thread(store.list_sessions)
                active_session_id = getattr(self.services, "active_session_id", None)
                if active_session_id is not None:
                    summaries = tuple(
                        summary for summary in summaries if summary.session_id != active_session_id
                    )
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: sessions_list_failed", exc, safe=True)
                self.sessions_panel.set_error("Could not read saved sessions.")
            else:
                self.sessions_panel.set_summaries(summaries)
        self._refresh_view()
        session_id = self.sessions_panel.selected_session_id
        if session_id is not None and self._section == "sessions":
            self._load_session_detail(session_id)

    def _load_session_detail(self, session_id: str) -> None:
        if self.sessions_panel.store is None or not self.is_running:
            return
        self.sessions_panel.set_loading(True)
        self._refresh_view()
        self.run_worker(
            self._read_session_detail(session_id),
            group="session-detail",
            exclusive=True,
        )

    async def _read_session_detail(self, session_id: str) -> None:
        try:
            detail = await asyncio.to_thread(self.sessions_panel.store.read, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_detail_failed", exc, safe=False)
            self.sessions_panel.set_error("Could not read this session.")
        else:
            self.sessions_panel.set_detail(session_id, detail)
        self._refresh_view()

    def _move_session_selection(self, offset: int) -> None:
        if self._section != "sessions":
            return
        session_id = self.sessions_panel.move_selection(offset)
        self._refresh_view()
        if session_id is not None:
            self._load_session_detail(session_id)

    def _selected_session_id(self) -> str | None:
        session_id = self.sessions_panel.selected_session_id
        if session_id is None:
            self.notify("Select a saved session first.", severity="warning")
        return session_id

    async def action_session_playback(self) -> None:
        if self._section != "sessions":
            return
        session_id = self._selected_session_id()
        toggle = getattr(self.services, "toggle_session_playback", None)
        if session_id is None or toggle is None:
            return
        try:
            await asyncio.to_thread(toggle, session_id)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_playback_failed", exc, safe=False)
            self.notify("Could not play this session.", severity="error")

    def action_session_rediarize(self) -> None:
        if self._section != "sessions":
            return
        session_id = self._selected_session_id()
        operation = getattr(self.services, "rediarize_session", None)
        if session_id is not None and operation is not None:
            self._start_session_job("Re-diarizing", operation, session_id)

    async def action_session_retranscribe(self) -> None:
        if self._section == "setup":
            await self.action_setup_test()
            return
        if self._section != "sessions":
            return
        session_id = self._selected_session_id()
        operation = getattr(self.services, "retranscribe_session", None)
        if session_id is not None and operation is not None:
            self._start_session_job("Re-transcribing", operation, session_id)

    def action_session_rename(self) -> None:
        if self._section != "sessions":
            self.action_doctor_recheck()
            return
        session_id = self._selected_session_id()
        labels = self.sessions_panel.speaker_labels
        if session_id is None or not labels:
            self.notify("This session has no speaker to rename.", severity="warning")
            return
        speaker_id = next(iter(labels))
        choices = ", ".join(f"{key} ({value})" for key, value in labels.items())
        self.push_screen(
            ConfigPrompt(
                f"Rename a speaker in {session_id}. Enter its ID: {choices}",
                initial=speaker_id,
            ),
            self._select_speaker_to_rename,
        )

    def _select_speaker_to_rename(self, speaker_id: str | None) -> None:
        if speaker_id is None:
            return
        label = self.sessions_panel.speaker_labels.get(speaker_id)
        if label is None:
            self.notify("That speaker is not in this session.", severity="warning")
            return
        self._pending_speaker_id = speaker_id
        self.push_screen(
            ConfigPrompt(f"New name for {label} ({speaker_id})", initial=label),
            self._rename_speaker,
        )

    def _rename_speaker(self, name: str | None) -> None:
        session_id = self.sessions_panel.selected_session_id
        speaker_id = self._pending_speaker_id
        self._pending_speaker_id = None
        store = self.sessions_panel.store
        if (
            name is None
            or not name.strip()
            or session_id is None
            or speaker_id is None
            or store is None
        ):
            return
        self._start_session_job(
            "Saving speaker name", store.rename_speaker, session_id, speaker_id, name
        )

    def action_session_export(self) -> None:
        if self._section != "sessions":
            return
        session_id = self._selected_session_id()
        if session_id is None or self.sessions_panel.store is None:
            return
        self.push_screen(
            ConfigPrompt(
                f"Export {session_id}. Enter format and output folder "
                "(for example: md ~/Documents).",
                initial="md ~/Documents",
            ),
            self._export_session,
        )

    def _export_session(self, value: str | None) -> None:
        session_id = self.sessions_panel.selected_session_id
        store = self.sessions_panel.store
        if value is None or session_id is None or store is None:
            return
        try:
            format_name, output_folder = value.split(maxsplit=1)
        except ValueError:
            self.notify(
                "Enter md, jsonl, srt, or txt followed by an output folder.", severity="warning"
            )
            return
        if format_name not in {"md", "jsonl", "srt", "txt"}:
            self.notify("Export format must be md, jsonl, srt, or txt.", severity="warning")
            return
        self._start_session_job(
            "Exporting",
            store.export,
            session_id,
            pathlib.Path(output_folder).expanduser(),
            format_name,
        )

    def action_session_delete(self) -> None:
        if self._section != "sessions":
            return
        session_id = self._selected_session_id()
        if session_id is None:
            return
        self._pending_delete_session = session_id
        self.push_screen(
            QuitConfirm(f"Delete session {session_id}? This action cannot be undone."),
            self._confirm_session_delete,
        )

    async def _confirm_session_delete(self, confirmed: bool | None) -> None:
        session_id = self._pending_delete_session
        self._pending_delete_session = None
        store = self.sessions_panel.store
        if not confirmed or session_id is None or store is None:
            return
        self._start_session_job("Deleting", store.delete, session_id)

    def _start_session_job(self, status: str, operation: Callable[..., object], *args) -> None:
        if self._session_job_status is not None:
            self.notify("A session job is already running.", severity="warning")
            return
        self._session_job_status = f"{status} session…"
        self._refresh_view()
        self.run_worker(
            self._run_session_job(status, operation, args),
            group="session-job",
            exclusive=True,
        )

    async def _run_session_job(
        self, status: str, operation: Callable[..., object], args: tuple[object, ...]
    ) -> None:
        try:
            result = await asyncio.to_thread(operation, *args)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: session_job_failed", exc, safe=False)
            self.notify(
                f"{status} failed. Check the application log for details.", severity="error"
            )
        else:
            if status == "Exporting":
                self.notify(f"Exported session to {result}.")
            elif status == "Deleting":
                self.notify("Session deleted.")
            else:
                self.notify(f"{status.removesuffix(' session…')} complete.")
            try:
                summaries = await asyncio.to_thread(self.sessions_panel.store.list_sessions)
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: sessions_list_failed", exc, safe=True)
                self.sessions_panel.set_error("Could not read saved sessions.")
            else:
                self.sessions_panel.set_summaries(summaries)
                session_id = self.sessions_panel.selected_session_id
                if session_id is not None and self._section == "sessions":
                    self._load_session_detail(session_id)
        finally:
            self._session_job_status = None
            if self.is_running:
                self._refresh_view()

    def _current_config(self) -> Config:
        editor = self.config_editor
        if editor is not None and editor.config is not None:
            return editor.config
        return Config.defaults()

    def _default_setup_test(self, step_id: str, config: Config) -> str:
        from stenographer.lib.config.paths import resolve_config_path

        config_dir = (
            self.config_editor.path.parent
            if self.config_editor is not None
            else resolve_config_path().parent
        )
        return test_setup_step(step_id, config, config_dir)

    def action_setup_next(self) -> None:
        self._advance_setup(skip=False)

    def action_setup_skip(self) -> None:
        self._advance_setup(skip=True)

    def _advance_setup(self, *, skip: bool) -> None:
        if self._section != "setup":
            return
        step_id = self.setup_wizard.step.step_id
        if (
            self.setup_wizard.will_finish
            and self.config_editor is not None
            and self.config_editor.dirty
            and not self._save_config()
        ):
            return
        if skip:
            self.setup_wizard.skip()
            log.info(fmt_event("hub", "setup_step_skipped", step=step_id))
        else:
            self.setup_wizard.next()
            log.info(fmt_event("hub", "setup_step_advanced", step=step_id))
        self._refresh_view()

    def action_setup_back(self) -> None:
        if self._section == "setup":
            self.setup_wizard.back()
            log.info(fmt_event("hub", "setup_step_back", step=self.setup_wizard.step.step_id))
            self._refresh_view()

    def action_setup_quick(self) -> None:
        if self._section == "setup":
            self.setup_wizard.start_quick()
            log.info(fmt_event("hub", "setup_quick_started"))
            self._refresh_view()

    async def action_setup_test(self) -> None:
        if self._section != "setup" or self.setup_wizard.finished:
            return
        step_id = self.setup_wizard.step.step_id
        log.info(fmt_event("hub", "setup_test_started", step=step_id))
        try:
            result = await asyncio.to_thread(
                self._setup_test, self.setup_wizard.step.step_id, self._current_config()
            )
        except Exception as exc:
            self.setup_wizard.record_test(f"failed: {exc}")
            log_failure(log, logging.ERROR, "hub: setup_test_failed", exc, safe=False, step=step_id)
            self.notify(f"Setup test failed: {exc}", severity="error")
        else:
            self.setup_wizard.record_test(result)
            log.info(fmt_event("hub", "setup_test_completed", step=step_id))
            self.notify(result)
        self._refresh_view()

    def action_setup_edit(self) -> None:
        if self._section != "setup" or self.config_editor is None:
            return
        key = self.setup_wizard.step.config_key
        editor = self.config_editor
        if key is None or editor.read_only:
            return
        value = editor.value(key)
        if value is None:
            initial = ""
        elif isinstance(value, tuple):
            initial = ", ".join(map(str, value))
        else:
            initial = str(value)
        choices: tuple[tuple[str, str], ...] | tuple[str, ...] | None = None
        prompt = f"Edit {key}"
        log.info(fmt_event("hub", "setup_edit_prompted", key=key))
        if key == "audio.input_device":
            from stenographer.cli.setup import workflow

            choices = tuple(workflow._audio_devices())
            labels = ", ".join(label for _, label in choices) or "no detected devices"
            prompt += f"; devices: {labels}; enter a number, name, or auto"
        elif key == "feedback.sound_pack":
            from stenographer.lib.sounds.packs import discover_sound_packs

            choices = tuple(discover_sound_packs(editor.path.parent))
            prompt += f"; packs: {', '.join(choices)}"
        self.push_screen(
            ConfigPrompt(prompt, initial=initial),
            lambda result: self._apply_setup_edit(key, result, choices),
        )

    def _apply_setup_edit(
        self,
        key: str,
        value: str | None,
        choices: tuple[tuple[str, str], ...] | tuple[str, ...] | None = None,
    ) -> None:
        if value is None or self.config_editor is None:
            return
        try:
            if key == "audio.input_device":
                from stenographer.cli.setup.workflow import parse_device_choice

                assert choices is not None
                value = parse_device_choice(
                    value,
                    self.config_editor.value(key),
                    choices,  # type: ignore[arg-type]
                )
                raw_value = "" if value is None else value
            elif key == "feedback.sound_pack":
                from stenographer.cli.sounds.workflow import parse_sound_pack_choice

                assert choices is not None
                current = str(self.config_editor.value(key))
                value = parse_sound_pack_choice(value, current, choices)  # type: ignore[arg-type]
                raw_value = value
            else:
                raw_value = value
            self.config_editor.edit(key, raw_value)
        except (ValueError, TypeError, ConfigError) as exc:
            log.info(fmt_event("hub", "setup_edit_failed", key=key, error=type(exc).__name__))
            self.notify(str(exc), severity="error")
        else:
            log.info(fmt_event("hub", "setup_config_edited", key=key))
        self._refresh_view()

    async def _write_setup_defaults(self) -> None:
        from stenographer.cli.setup.workflow import save_defaults
        from stenographer.lib.config.paths import resolve_config_path

        path = self.config_editor.path if self.config_editor is not None else resolve_config_path()
        try:
            result = await asyncio.to_thread(save_defaults, path)
        except (ConfigError, ConfigPersistenceError) as exc:
            log_failure(log, logging.ERROR, "hub: setup_defaults_failed", exc, safe=True)
            self.notify(str(exc), severity="error")
            return
        self.config_editor = ConfigEditor(path)
        update_config = getattr(self.services, "update_config", None)
        if update_config is not None:
            update_config(self._current_config())
        suffix = f"; backup: {result.backup_path}" if result.backup_path is not None else ""
        log.info(fmt_event("hub", "setup_defaults_written", changed=result.changed))
        self.notify(f"Wrote default configuration to {result.path}{suffix}")
        self._refresh_view()

    def action_setup_download_model(self) -> None:
        if self._section != "setup" or self.setup_wizard.step.step_id != "models":
            return
        self._pending_model = self._current_config().asr.model
        log.info(fmt_event("hub", "setup_model_download_prompted"))
        self.push_screen(
            QuitConfirm(f"Download ASR model {self._pending_model} now?"),
            self._confirm_model_download,
        )

    async def _confirm_model_download(self, confirmed: bool | None) -> None:
        model = self._pending_model
        self._pending_model = None
        log.info(fmt_event("hub", "setup_model_download_confirmed", confirmed=bool(confirmed)))
        if not confirmed or model is None:
            return
        try:
            await asyncio.to_thread(self._model_download, model)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_model_download_failed", exc, safe=True)
            self.notify(f"Model download failed: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "setup_model_download_completed"))
            self.notify(f"Model {model} is cached.")

    def _request_doctor_check(self) -> None:
        self._doctor_loading = True
        self._refresh_view()
        self.run_worker(self._load_doctor_report(), group="doctor", exclusive=True)

    async def _load_doctor_report(self) -> None:
        try:
            report = await asyncio.to_thread(
                self._doctor_probe,
                self._current_config(),
                self.config_editor.path if self.config_editor is not None else None,
            )
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: doctor_probe_failed", exc, safe=False)
            report = DoctorReport(
                (
                    DoctorCheck(
                        "doctor_probe",
                        "system probe",
                        "engine and desktop",
                        "fail",
                        str(exc),
                        "Check the application log for details.",
                    ),
                ),
                (),
            )
        self._doctor_report = report
        log.info(
            fmt_event(
                "hub",
                "doctor_checked",
                warn_count=report.warn_count,
                fail_count=report.fail_count,
            )
        )
        self._doctor_index = report.first_issue_index
        self._doctor_details = False
        self._doctor_loading = False
        self._refresh_view()

    def action_doctor_recheck(self) -> None:
        if self._section == "doctor":
            log.info(fmt_event("hub", "doctor_recheck_requested"))
            self._request_doctor_check()

    def _move_doctor_check(self, offset: int) -> None:
        report = self._doctor_report
        if self._section != "doctor" or report is None or not report.checks:
            return
        self._doctor_index = (self._doctor_index + offset) % len(report.checks)
        self._doctor_details = False
        log.info(
            fmt_event(
                "hub", "doctor_check_selected", check=report.checks[self._doctor_index].check_id
            )
        )
        self._refresh_view()

    def action_doctor_fix(self) -> None:
        report = self._doctor_report
        if self._section != "doctor" or report is None or not report.checks:
            return
        check = report.checks[self._doctor_index]
        if check.status not in {"warn", "fail"}:
            log.info(fmt_event("hub", "doctor_fix_not_needed", check=check.check_id))
            self.notify("This check does not need a fix.")
            return
        step_by_check = {
            "key_injector_ok": "input_access",
            "hotkey_access_ok": "input_access",
            "has_mic": "microphone",
            "system_capture": "microphone",
            "model_cached": "models",
            "live_models_cached": "models",
            "ffmpeg": "models",
            "cue_player": "sounds",
            "system_service": "system_service",
        }
        log.info(fmt_event("hub", "doctor_fix_selected", check=check.check_id))
        target = step_by_check.get(check.check_id, "input_access")
        self.setup_wizard.index = next(
            index for index, step in enumerate(self.setup_wizard.steps) if step.step_id == target
        )
        self.setup_wizard.quick = False
        self.setup_wizard.finished = False
        self._select_section("setup")

    def action_doctor_open_log(self) -> None:
        if self._section != "doctor":
            return
        log.info(fmt_event("hub", "doctor_log_open_requested"))
        try:
            opened = self._open_log()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: doctor_log_open_failed", exc, safe=False)
            opened = False
        if not opened:
            self.notify("The application log is not available.", severity="warning")

    def action_doctor_copy_report(self) -> None:
        if self._section != "doctor" or self._doctor_report is None:
            return
        text = self._doctor_report.report_text()
        try:
            if self._copy_report is None:
                self.copy_to_clipboard(text)
            else:
                self._copy_report(text)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: doctor_report_copy_failed", exc, safe=False)
            self.notify("Could not copy the doctor report.", severity="error")
            return
        log.info(fmt_event("hub", "doctor_report_copied"))
        self.notify("Doctor report copied.")

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
            self._section in {"config", "setup"}
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
