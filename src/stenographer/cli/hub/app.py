# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual shell for the stenographer hub."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_panel import DoctorPanel
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, build_report
from stenographer.cli.hub.files_view import FilesPanel
from stenographer.cli.hub.live_view import LiveView
from stenographer.cli.hub.selection import append_line
from stenographer.cli.hub.sessions_view import SessionsPanel
from stenographer.cli.hub.setup_panel import SetupPanel
from stenographer.cli.hub.setup_state import SetupWizard
from stenographer.cli.hub.setup_wizard import render as render_setup
from stenographer.cli.hub.setup_wizard import test_step as test_setup_step
from stenographer.cli.live.rename_dialog import RenameDialog
from stenographer.cli.shared.no_background_css import NO_BACKGROUND_CSS
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

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
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
        Binding("tab", "files_next_area", "Change Files panel focus", priority=True),
        ("o", "toggle_files_options", "Edit Files options"),
        ("b", "setup_back", "Previous setup step"),
        ("s", "toggle_system", "System audio or skip setup step"),
        ("t", "session_retranscribe", "Re-transcribe session or test setup step"),
        ("e", "setup_edit", "Edit setup value"),
        ("shift+q", "setup_quick", "Quick setup"),
        ("m", "toggle_mic", "Microphone or download model"),
        ("v", "toggle_live_view", "Toggle mixed or split transcript"),
        ("r", "session_rename", "Rename session or live speaker; re-check Doctor"),
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
    CSS = (
        NO_BACKGROUND_CSS
        + """
    #hub-layout {
        height: 1fr;
        padding: 1;
    }
    #sidebar-column {
        width: 25;
        height: 1fr;
        margin-right: 1;
    }
    #sidebar {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        margin-bottom: 1;
        border: round #3a4150;
        border-title-color: #5fd7ff;
        border-title-style: bold;
    }
    #sidebar-card {
        width: 1fr;
        height: 7;
        padding: 0 1;
        border: round #3a4150;
    }
    #section-content {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        border: round #3a4150;
        overflow-y: auto;
    }
    #setup-panel, #doctor-panel {
        width: 1fr;
        height: 1fr;
    }
    #setup-steps {
        width: 34%;
        height: 1fr;
        padding: 1;
        margin-right: 1;
        border: round #3a4150;
        border-title-color: ansi_default;
    }
    #setup-detail {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        border: round #3a4150;
        border-title-color: ansi_default;
    }
    #doctor-groups {
        width: 1fr;
        height: 13;
    }
    #doctor-input-group, #doctor-engine-group {
        width: 1fr;
        height: 13;
        padding: 1;
        border: round #3a4150;
        border-title-color: ansi_default;
    }
    #doctor-input-group {
        margin-right: 1;
    }
    #doctor-issue {
        width: 1fr;
        height: 8;
        margin-top: 1;
        padding: 1;
        border: round #3a4150;
        border-title-color: ansi_default;
    }
    #doctor-warnings {
        width: 1fr;
        height: 1fr;
        min-height: 5;
        margin-top: 1;
        padding: 1;
        border: round #3a4150;
        border-title-color: ansi_default;
        overflow-y: auto;
    }
    #live-view {
        width: 1fr;
        height: 1fr;
    }
    #live-top {
        width: 1fr;
        height: 6;
    }
    #live-rec, #live-mic {
        margin-right: 1;
    }
    #live-rec, #live-mic, #live-system {
        width: 1fr;
        height: 6;
        padding: 0 1;
    }
    #live-rec {
        border: round #ff875f;
        border-title-color: #ff875f;
        border-title-style: bold;
    }
    #live-mic {
        border: round #5fd7ff;
    }
    #live-system {
        border: round #ffaf5f;
    }
    #live-transcript {
        width: 1fr;
        height: 1fr;
        margin-top: 1;
        padding: 0 1;
        border: round #3a4150;
        border-title-color: ansi_default;
        border-title-style: bold;
        overflow-y: auto;
    }
    #files-browser-scroll, #files-options-scroll, #files-queue-scroll, #files-preview-scroll {
        border-title-color: ansi_default;
        border-title-style: bold;
    }
    #key-hints {
        height: 1;
        padding: 0 2;
        color: ansi_default;
    }
    """
    )

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
        files_home: pathlib.Path | None = None,
    ) -> None:
        super().__init__(ansi_color=True)
        self.services = services
        self.files_panel = FilesPanel(
            home=files_home,
            output_folder=getattr(services, "files_output_folder", None),
            id="files-panel",
        )
        self._files_submitting = 0
        self.sessions_panel = SessionsPanel(
            getattr(services, "session_store", None), id="sessions-panel"
        )
        self.live_view = LiveView(id="live-view")
        self.setup_panel = SetupPanel(id="setup-panel")
        self.doctor_panel = DoctorPanel(id="doctor-panel")
        self._sidebar_cards: dict[str, str | Text] = {}
        self._files_sidebar_card_custom = False
        self._session_job_status: str | None = None
        self._pending_speaker_id: str | None = None
        self._pending_delete_session: str | None = None
        self.config_editor = config_editor or (
            ConfigEditor(config_path) if config_path is not None else None
        )
        self._hub_screen: Screen | None = None
        self._section = "live"
        self._activity_status: str | None = None
        self._pending_section: str | None = None
        self._pending_quit = False
        self._live_split = False
        self._cpu_percent: float | None = None
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

    @staticmethod
    def _format_key_hints(*items: tuple[str, str]) -> Text:
        hints = Text()
        for index, (key, description) in enumerate(items):
            if index:
                hints.append("   ", style="default")
            hints.append(key, style="bold #5fd7ff")
            hints.append(f" {description}", style="default")
        return hints

    @staticmethod
    def _format_live_key_hints(split: bool) -> Text:
        hints = Text()
        items = (
            ("space", "pause/resume"),
            ("m", "mic"),
            ("s", "system"),
            ("v", None),
            ("r", "rename"),
            ("q", "stop/save"),
            ("1-6", "sections"),
        )
        for index, (key, description) in enumerate(items):
            if index:
                hints.append("   ", style="default")
            hints.append(key, style="bold #5fd7ff")
            if description is not None:
                hints.append(f" {description}", style="default")
                continue
            hints.append(" view: ", style="default")
            hints.append("mixed", style="default" if split else "bold")
            hints.append(" / ", style="default")
            hints.append("split", style="bold" if split else "default")
        return hints

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-layout"):
            with Vertical(id="sidebar-column"):
                yield Static("", id="sidebar", markup=False)
                yield Static("", id="sidebar-card", markup=False)
            yield Static("", id="section-content", markup=False)
            yield self.setup_panel
            yield self.doctor_panel
            yield self.live_view
            yield self.files_panel
            yield self.sessions_panel
        yield Static(
            "space start recording   1-6 sections   q quit",
            id="key-hints",
            markup=False,
        )

    def on_mount(self) -> None:
        self._hub_screen = self.screen
        self.query_one("#sidebar", Static).border_title = "stenographer"
        self._sample_cpu()
        self.set_interval(0.1, self._refresh_live_view)
        self.set_interval(1.0, self._sample_cpu)
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
        close_files = getattr(self.services, "close_files", None)
        if close_files is not None:
            try:
                close_files()
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: files_cleanup_failed", exc, safe=True)

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
        screen = self._hub_screen
        if screen is None or not self.is_running or not self.is_mounted(screen):
            return
        sidebar = Text()
        for index, (section, label) in enumerate(_SECTIONS, start=1):
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
            append_line(
                sidebar,
                f"{index} {label:<8} {badge}",
                selectable=True,
                selected=section == self._section,
            )
        screen.query_one("#sidebar", Static).update(sidebar)

        session = self._live_session() if self._section == "live" else None
        if self._section == "live":
            self.set_sidebar_card(self._live_sidebar_card(session), section="live")
        elif self._section == "files":
            if not self._files_sidebar_card_custom:
                self._sidebar_cards["files"] = self._files_sidebar_card()
            self.query_one("#sidebar-card", Static).update(self._sidebar_cards.get("files", ""))
        elif self._section == "doctor" and self._doctor_report is not None:
            self.query_one("#sidebar-card", Static).update(self._doctor_report.sidebar_summary())
        elif self._section == "doctor" and self._doctor_loading:
            self.query_one("#sidebar-card", Static).update("summary\nChecking…")
        else:
            self.query_one("#sidebar-card", Static).update(
                self._sidebar_cards.get(self._section, "")
            )
        self.query_one("#sidebar-card", Static).display = self._section != "setup"

        title = next(label for section, label in _SECTIONS if section == self._section)
        content = _PLACEHOLDERS[self._section]
        if self._section == "live":
            self.live_view.refresh_view(
                session,
                mic_device=self._mic_device_name(),
                split=self._live_split,
                recording_active=self.services.recording and session is None,
            )
            content = "" if self._activity_status is None else self._activity_status
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
        section_view = screen.query_one("#section-content", Static)
        show_activity = self._section == "live" and self._activity_status is not None
        section_view.display = (
            self._section
            not in {
                "live",
                "files",
                "sessions",
                "setup",
                "doctor",
            }
            or show_activity
        )
        self.setup_panel.display = self._section == "setup"
        self.doctor_panel.display = self._section == "doctor"
        if self._section == "setup":
            self.setup_panel.refresh_view(self.setup_wizard, self._current_config())
        elif self._section == "doctor":
            self.doctor_panel.refresh_view(
                self._doctor_report,
                selected_index=self._doctor_index,
                details=self._doctor_details,
                loading=self._doctor_loading,
            )
        self.live_view.display = self._section == "live" and not show_activity
        self.files_panel.display = self._section == "files"
        self.sessions_panel.display = self._section == "sessions"
        if self._section == "files":
            self._refresh_files_view()
        self.sessions_panel.set_job_status(self._session_job_status)
        if self._section == "config" and self.config_editor is not None:
            content = self.config_editor.render()
        if self._activity_status is not None:
            content = self._activity_status
        section_view.border_title = title
        section_view.update(content)
        hints = screen.query_one("#key-hints", Static)
        if self._section == "config":
            hints.update(
                self._format_key_hints(
                    ("enter", "edit"),
                    ("u", "undo"),
                    ("D", "reset"),
                    ("/", "search"),
                    ("ctrl+s", "save"),
                    ("←/→", "group"),
                    ("↑/↓", "key"),
                )
            )
        elif self._section == "setup":
            hints.update(
                self._format_key_hints(
                    ("enter", "next"),
                    ("b", "back"),
                    ("s", "skip"),
                    ("t", "test"),
                    ("e", "edit"),
                    ("D", "defaults"),
                    ("Q", "quick"),
                )
            )
        elif self._section == "doctor":
            hints.update(
                self._format_key_hints(
                    ("r", "re-check"),
                    ("enter", "details"),
                    ("f", "fix in Setup"),
                    ("l", "open log"),
                    ("c", "copy report"),
                )
            )
        elif self._section == "sessions":
            hints.update(
                self._format_key_hints(
                    ("↑/↓", "session"),
                    ("p", "play"),
                    ("d", "re-diarize"),
                    ("t", "re-transcribe"),
                    ("r", "rename"),
                    ("x", "export"),
                    ("del", "delete"),
                )
            )
        elif self._section == "live":
            hints.update(self._format_live_key_hints(self._live_split))
        elif self._section == "files":
            hints.update(
                self._format_key_hints(
                    ("↑/↓", "move"),
                    ("tab", "focus"),
                    ("/", "search"),
                    ("enter", "queue"),
                    ("space", "select"),
                    ("o", "options"),
                    ("x", "cancel"),
                    ("e", "open result"),
                    ("1-6", "sections"),
                )
            )
        else:
            hints.update(
                self._format_key_hints(
                    ("space", "start recording"), ("1-6", "sections"), ("q", "quit")
                )
            )

    def set_sidebar_card(self, content: str | Text, *, section: str | None = None) -> None:
        """Set the shared sidebar card content for one hub section."""
        section = section or self._section
        self._sidebar_cards[section] = content
        if section == "files":
            self._files_sidebar_card_custom = True
        screen = self._hub_screen
        if section == self._section and screen is not None and self.is_mounted(screen):
            screen.query_one("#sidebar-card", Static).update(content)

    def _live_sidebar_card(self, session) -> Text:
        config = self._current_config()
        model = session.model_name if session is not None else config.asr.model
        model = model.rsplit("/", 1)[-1].removeprefix("faster-whisper-")
        queue = session.queue_depth if session is not None else 0
        failed = session.failed_phrase_count if session is not None else 0
        card = Text(f"engine\n{model} {config.asr.compute_type}\nqueue {queue} · failed {failed}\n")
        card.append(self._cpu_sidebar_line())
        return card

    def _files_sidebar_card(self) -> Text:
        config = self._current_config()
        model = (
            config.asr.model.rsplit("/", 1)[-1].removeprefix("faster-whisper-").removesuffix("-ct2")
        )
        card = Text(f"engine\n{model} {config.asr.compute_type}\n")
        card.append(self._cpu_sidebar_line())
        return card

    def _cpu_sidebar_line(self) -> str:
        cpu = self._cpu_percent
        cpu_text = "—" if cpu is None else f"{cpu:.0f}%"
        if cpu is None:
            cpu_bar = "▕········▏"
        else:
            filled = min(8, max(0, int(cpu / 100 * 8)))
            cpu_bar = f"▕{'█' * filled}{'·' * (8 - filled)}▏"
        return f"cpu {cpu_bar} {cpu_text}"

    def _live_session(self):
        return getattr(self.services, "session", None)

    def _mic_device_name(self) -> str:
        device = self._current_config().audio.input_device
        return str(device) if device else "Default input"

    def _refresh_live_view(self) -> None:
        if self._section == "live":
            self._refresh_view()
        elif self._section == "files":
            self._refresh_files_view()

    def _refresh_files_view(self) -> None:
        jobs = getattr(self.services, "files_jobs", ())
        if callable(jobs):
            jobs = jobs()
        self.files_panel.set_jobs(tuple(jobs))

    def _sample_cpu(self) -> None:
        if self._section not in {"live", "files"}:
            return
        import psutil

        self._cpu_percent = psutil.cpu_percent(interval=None)
        self._refresh_view()

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
        if self._section == "files":
            self.files_panel.move_selection(offset)
        elif self._section == "config" and self.config_editor is not None:
            self.config_editor.move_key(offset)
            self._refresh_view()

    def action_edit_config(self) -> None:
        if self._section == "files":
            if self.files_panel.focus_area == "options":
                self._edit_files_option()
            else:
                self._queue_selected_files()
            return
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
        if self._section == "files":
            self.push_screen(
                ConfigPrompt("Search audio files", initial=self.files_panel.search_term),
                self._search_files,
            )
            return
        editor = self.config_editor
        if self._section != "config" or editor is None:
            return
        if editor.read_only:
            return
        self.push_screen(
            ConfigPrompt("Search configuration keys", initial=""),
            self._search_config,
        )

    def _search_files(self, term: str | None) -> None:
        if term is not None:
            self.files_panel.set_search(term)
            log.info(fmt_event("hub", "files_search_updated", active=bool(term.strip())))

    def action_files_next_area(self) -> None:
        if self._section == "files" and self.screen is self._hub_screen:
            self.files_panel.cycle_focus()
            log.info(fmt_event("hub", "files_focus_changed", area=self.files_panel.focus_area))

    def action_toggle_files_options(self) -> None:
        if self._section == "files":
            self.files_panel.toggle_options()
            log.info(fmt_event("hub", "files_options_toggled", open=self.files_panel.options_open))

    def _edit_files_option(self) -> None:
        panel = self.files_panel
        option = panel.selected_option
        log.info(fmt_event("hub", "files_option_edit_started", option=option.replace(" ", "_")))
        if option == "diarize":
            panel.diarize = not panel.diarize
            panel.refresh_display()
        elif option == "refine":
            panel.refine = not panel.refine
            panel.refresh_display()
        elif option == "output format":
            formats = ("md", "jsonl", "srt", "txt")
            panel.output_format = formats[(formats.index(panel.output_format) + 1) % len(formats)]
            panel.refresh_display()
        elif option == "speaker count":
            count = "auto" if panel.speaker_count is None else str(panel.speaker_count)
            self.push_screen(
                ConfigPrompt("Speaker count (auto or a positive number)", initial=count),
                self._set_file_speaker_count,
            )
        elif option == "output folder":
            self.push_screen(
                ConfigPrompt("Output folder", initial=str(panel.output_folder)),
                self._set_file_output_folder,
            )

    def _set_file_speaker_count(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        try:
            count = None if normalized == "auto" else int(normalized)
            if count is not None and count < 1:
                raise ValueError
        except ValueError:
            self.notify("Speaker count must be auto or a positive number.", severity="warning")
            return
        self.files_panel.speaker_count = count
        self.files_panel.refresh_display()
        log.info(fmt_event("hub", "files_speaker_count_changed", automatic=count is None))

    def _set_file_output_folder(self, value: str | None) -> None:
        if value is not None and value.strip():
            self.files_panel.output_folder = pathlib.Path(value).expanduser()
            self.files_panel.refresh_display()
            log.info(fmt_event("hub", "files_output_folder_changed"))

    def _queue_selected_files(self) -> None:
        selected = self.files_panel.selected_entry
        paths = self.files_panel.enter()
        if not paths:
            if selected is not None and selected.is_dir:
                log.info(fmt_event("hub", "files_directory_opened"))
            return
        if self.config_editor is not None and self.config_editor.read_only:
            self.notify(
                "Fix the invalid configuration before transcribing files.", severity="error"
            )
            return
        options = {
            "diarize": self.files_panel.diarize,
            "speaker_count": self.files_panel.speaker_count,
            "refine": self.files_panel.refine,
            "output_format": self.files_panel.output_format,
            "output_folder": self.files_panel.output_folder,
        }
        self._files_submitting += len(paths)
        log.info(fmt_event("hub", "files_queue_requested", count=len(paths)))
        self._refresh_view()
        self.run_worker(self._submit_files(paths, options), group="files-submit")

    async def _submit_files(
        self, paths: tuple[pathlib.Path, ...], options: dict[str, object]
    ) -> None:
        submit = getattr(self.services, "submit_file", None)
        if submit is None:
            self.notify("File transcription is not available.", severity="error")
            self._files_submitting = max(0, self._files_submitting - len(paths))
            self._refresh_view()
            return
        for path in paths:
            try:
                await asyncio.to_thread(
                    submit,
                    path,
                    **options,
                )
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: file_submit_failed", exc, safe=True)
                self.notify("Could not queue this file.", severity="error")
            finally:
                self._files_submitting = max(0, self._files_submitting - 1)
                self._refresh_files_view()
        if self.is_running:
            self._refresh_view()

    def _cancel_selected_file(self) -> None:
        if self.files_panel.focus_area != "queue":
            self.notify("Focus the queue to select a Files job.", severity="warning")
            return
        job = self.files_panel.selected_job
        if job is None:
            self.notify("Select a Files job first.", severity="warning")
            return
        cancel = getattr(self.services, "cancel_file", None)
        try:
            cancelled = cancel(job) if cancel is not None else job.cancel()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: file_cancel_failed", exc, safe=True)
            self.notify("Could not cancel this Files job.", severity="error")
            return
        log.info(
            fmt_event("hub", "files_job_cancel_requested", job_id=getattr(job, "id", "unknown"))
        )
        if not cancelled:
            self.notify("This Files job has already finished.", severity="warning")
        self._refresh_files_view()

    def _open_files_result(self) -> None:
        if self.files_panel.focus_area != "queue":
            self.notify("Focus the queue to select a Files result.", severity="warning")
            return
        job = self.files_panel.selected_job
        output_path = None if job is None else getattr(job, "output_path", None)
        if output_path is None:
            self.notify("This Files job has no saved result yet.", severity="warning")
            return
        log.info(
            fmt_event(
                "hub", "files_result_folder_open_requested", job_id=getattr(job, "id", "unknown")
            )
        )
        opener = getattr(self.services, "open_files_result", None)
        if opener is None:
            self.notify("Could not open the result folder.", severity="error")
            return
        try:
            opened = opener(output_path)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: file_result_open_failed", exc, safe=True)
            opened = False
        if not opened:
            self.notify("Could not open the result folder.", severity="warning")

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
        if self._section == "doctor":
            self.action_doctor_recheck()
            return
        if self._section == "live":
            self.action_rename_live_speaker()
            return
        if self._section != "sessions":
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
        if self._section == "files":
            self._cancel_selected_file()
            return
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
        if self._section == "files":
            self._open_files_result()
            return
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

    def action_start_recording(self) -> None:
        if self._activity_status is not None:
            return
        if self._section == "files":
            if self.files_panel.focus_area == "options":
                self._edit_files_option()
            elif self.files_panel.focus_area == "browser":
                self.files_panel.toggle_selected_file()
                log.info(
                    fmt_event(
                        "hub",
                        "files_selection_changed",
                        count=len(self.files_panel.selected_paths),
                    )
                )
            return
        if self._section != "live":
            return
        if self.services.recording:
            session = self._live_session()
            if session is None:
                return
            action = session.resume if session.paused else session.pause
            status = "Resuming recording..." if session.paused else "Pausing recording..."
            self._run_live_action(action, status=status, name="toggle-recording")
            return
        if self.config_editor is not None and self.config_editor.read_only:
            self.notify("Fix the invalid configuration before recording.", severity="error")
            return
        self._activity_status = "Starting recording..."
        self._refresh_view()
        self.run_worker(self._start_recording(), name="start-recording", group="hub-work")

    async def _start_recording(self) -> None:
        try:
            await asyncio.to_thread(self.services.start_recording)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_start_failed", exc, safe=True)
            self.notify(f"Could not start recording: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "recording_started"))
        self._activity_status = None
        self._refresh_view()

    def action_toggle_mic(self) -> None:
        if self._section == "setup":
            self.action_setup_download_model()
            return
        session = self._live_session()
        if self._section == "live" and session is not None:
            self._run_live_action(
                lambda: session.toggle("mic"), status="Toggling microphone...", name="toggle-mic"
            )

    def action_toggle_system(self) -> None:
        if self._section == "setup":
            self.action_setup_skip()
            return
        session = self._live_session()
        if self._section == "live" and session is not None:
            self._run_live_action(
                lambda: session.toggle("system"),
                status="Toggling system audio...",
                name="toggle-system",
            )

    def _run_live_action(self, action: Callable[[], None], *, status: str, name: str) -> None:
        if self._activity_status is not None:
            return
        self._activity_status = status
        self._refresh_view()
        self.run_worker(self._perform_live_action(action, name), name=name, group="hub-work")

    async def _perform_live_action(self, action: Callable[[], None], name: str) -> None:
        try:
            await asyncio.to_thread(action)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: live_action_failed", exc, safe=True, action=name)
            self.notify(f"Could not update the live session: {exc}", severity="error")
        self._activity_status = None
        self._refresh_view()

    def action_toggle_live_view(self) -> None:
        if self._section != "live":
            return
        self._live_split = not self._live_split
        view = "split" if self._live_split else "mixed"
        log.info(fmt_event("hub", "live_view_toggled", view=view))
        self._refresh_view()

    def action_rename_live_speaker(self) -> None:
        if self._section == "doctor":
            self.action_doctor_recheck()
            return
        session = self._live_session()
        if self._section != "live" or session is None:
            return
        speakers = session.speakers
        if not speakers:
            self.notify("No system speakers are available to rename.")
            return
        self.push_screen(
            RenameDialog(speakers),
            lambda result: self._rename_live_speaker(session, result),
        )

    def _rename_live_speaker(self, session, value: tuple[str, str] | None) -> None:
        if value is None:
            return
        speaker_id, name = value
        try:
            session.rename(speaker_id, name)
        except ValueError as exc:
            self.notify(str(exc))
            return
        self._refresh_view()

    def _files_running(self) -> bool:
        return self._files_submitting > 0 or bool(getattr(self.services, "files_running", False))

    def action_request_quit(self) -> None:
        if self._activity_status is not None:
            return
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
        elif self._files_running():
            self._prompt_files_quit()
        else:
            self.exit()

    def _confirm_recording_quit(self, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "quit_confirmed", work="recording", confirmed=bool(confirmed)))
        if not confirmed:
            return
        self._activity_status = "Saving recording..."
        self._refresh_view()
        self.run_worker(self._stop_recording_and_quit(), name="save-recording", group="hub-work")

    async def _stop_recording_and_quit(self) -> None:
        try:
            await asyncio.to_thread(self.services.stop_recording)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: recording_stop_failed", exc, safe=True)
            self.notify(f"Could not save the recording: {exc}", severity="error")
            self._activity_status = None
            self._refresh_view()
            return
        self._activity_status = None
        self._refresh_view()
        if self._files_running():
            self._prompt_files_quit()
        else:
            self.exit()

    def _prompt_files_quit(self) -> None:
        log.info(fmt_event("hub", "quit_prompted", work="files"))
        self.push_screen(
            QuitConfirm("Cancel the running Files job before quitting?"),
            self._confirm_files_quit,
        )

    def _confirm_files_quit(self, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "quit_confirmed", work="files", confirmed=bool(confirmed)))
        if not confirmed:
            return
        self._activity_status = "Canceling Files job..."
        self._refresh_view()
        self.run_worker(self._cancel_files_and_quit(), name="cancel-files", group="hub-work")

    async def _cancel_files_and_quit(self) -> None:
        try:
            await asyncio.to_thread(self.services.cancel_files)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: files_cancel_failed", exc, safe=True)
            self.notify(f"Could not cancel the Files job: {exc}", severity="error")
            self._activity_status = None
            self._refresh_view()
            return
        self._activity_status = None
        self.exit()
