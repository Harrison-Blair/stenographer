# SPDX-License-Identifier: GPL-3.0-or-later
"""Textual shell for the stenographer hub: three screens, sidebar, help and quit."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import App
from textual.binding import Binding

from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import (
    DoctorReport,
    ModelEntry,
    build_report,
    default_model_download,
    default_model_status,
)
from stenographer.cli.hub.engine_sampler import EngineSampler
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.library_screen import LibraryScreen
from stenographer.cli.hub.record_screen import RecordScreen
from stenographer.cli.hub.settings_screen import SettingsScreen
from stenographer.cli.hub.setup_test import test_step as test_setup_step
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.clock import Clock
from stenographer.cli.hub.widgets.help_overlay import HelpOverlay
from stenographer.cli.hub.widgets.sidebar import CardButtons, Sidebar
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.shared.no_background_css import NO_BACKGROUND_CSS
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
from stenographer.lib.config.models import Config
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from rich.console import RenderableType

log = logging.getLogger(__name__)


class HubApp(App[None]):
    """Show Record, Library and Settings while shared work continues in the services."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("1", "show_screen('record')", "Record screen"),
        ("2", "show_screen('library')", "Library screen"),
        ("3", "show_screen('settings')", "Settings screen"),
        Binding("question_mark", "help", "Help for this screen", key_display="?"),
        ("q", "request_quit", "Quit"),
        ("ctrl+c", "request_quit", "Quit"),
    ]
    CSS = (
        NO_BACKGROUND_CSS
        + HubButton.APP_CSS
        + """
    #hub-layout {
        height: 1fr;
        padding: 1 1 0 1;
    }
    #screen-body {
        width: 1fr;
        height: 1fr;
    }
    #transcript-scroll-content {
        width: 1fr;
        height: auto;
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
        model_status: Callable[[], tuple[ModelEntry, ...]] | None = None,
        doctor_probe: Callable[[Config], DoctorReport] | None = None,
        open_log: Callable[[pathlib.Path], bool] | None = None,
        copy_report: Callable[[str], None] | None = None,
        files_home: pathlib.Path | None = None,
        engine_sampler: EngineSampler | None = None,
    ) -> None:
        super().__init__(ansi_color=True)
        self.services = services
        self.config_editor = config_editor or (
            ConfigEditor(config_path) if config_path is not None else None
        )
        self.activity_status: str | None = None
        self.engine_sampler = engine_sampler or EngineSampler(services)
        self._context_cards: dict[str, tuple[str, RenderableType, CardButtons, frozenset[str]]] = {}
        self._busy: dict[str, str] = {}
        self._busy_lock = threading.Lock()
        if open_log is None:
            from stenographer.cli.hub.doctor_view import default_log_opener

            open_log = default_log_opener
        self.checks_tab = ChecksTab(
            doctor_probe=doctor_probe or build_report,
            setup_test=setup_test or self._default_setup_test,
            model_download=model_download or default_model_download,
            model_status=model_status or default_model_status,
            open_log=open_log,
            copy_report=copy_report,
            id="checks-tab",
        )
        self.record_screen = RecordScreen()
        self.library_screen = LibraryScreen(services, files_home=files_home)
        self.settings_screen = SettingsScreen(self.checks_tab)
        self.hub_screens: dict[str, HubScreen] = {
            "record": self.record_screen,
            "library": self.library_screen,
            "settings": self.settings_screen,
        }
        for name, screen in self.hub_screens.items():
            self.add_mode(name, lambda screen=screen: screen)

    @property
    def current_hub_screen(self) -> HubScreen | None:
        return self.hub_screens.get(self.current_mode)

    def on_mount(self) -> None:
        self.switch_mode("record")
        self.engine_sampler.sample()
        self.set_interval(0.1, self._refresh_live)
        self.set_interval(1.0, self._sample_engine)
        if self.config_editor is not None and self.config_editor.read_only:
            self.notify(
                "Invalid configuration. Open Settings to view the error and fix "
                f"{self.config_editor.path}.",
                severity="error",
            )
        self.library_screen.load_sessions()
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

    # Shell contracts (README §4.1a)

    def show_screen(self, name: str) -> None:
        """Show ``record``, ``library`` or ``settings``; guard unsaved settings."""
        if name == "settings":
            self._switch(name)
        else:
            self._guard_settings(lambda: self._switch(name))

    def show_library(self, session_id: str | None = None) -> None:
        """Show Library; select ``session_id``, reloading the list when needed."""

        def proceed() -> None:
            self._switch("library")
            if session_id is not None:
                self.library_screen.show_session(session_id)

        self._guard_settings(proceed)

    def open_setting(self, key: str) -> None:
        """Show Settings with the tab and row of a dotted key; unsaved changes stay."""
        self._switch("settings")
        self.settings_screen.open_setting(key)

    def set_context_card(
        self,
        screen: str,
        content: RenderableType,
        *,
        title: str,
        buttons: CardButtons = (),
        disabled: frozenset[str] = frozenset(),
    ) -> None:
        """Set the context card of one screen; it shows while that screen shows.

        Each ``(label, key, run)`` of ``buttons`` shows as a ``[key] label``
        button under the text; a click calls ``run``. A button whose key is in
        ``disabled`` shows as disabled.
        """
        self._context_cards[screen] = (title, content, buttons, disabled)

    def try_acquire_session(self, session_id: str, owner: str) -> bool:
        """Mark a session busy for ``owner``; false when another owner holds it."""
        with self._busy_lock:
            holder = self._busy.get(session_id)
            if holder is not None and holder != owner:
                return False
            self._busy[session_id] = owner
            return True

    def release_session(self, session_id: str, owner: str) -> None:
        """Clear the busy mark only when ``owner`` holds it."""
        with self._busy_lock:
            if self._busy.get(session_id) == owner:
                del self._busy[session_id]

    def is_busy(self, session_id: str) -> bool:
        with self._busy_lock:
            return session_id in self._busy

    # Navigation

    def action_show_screen(self, name: str) -> None:
        self.show_screen(name)

    def _switch(self, name: str) -> None:
        if name == self.current_mode:
            self.refresh_view()
            return
        self.switch_mode(name)
        log.info(fmt_event("hub", "screen_changed", screen=name))
        if name == "library":
            self.library_screen.load_sessions()
        elif name == "record":
            self.record_screen.refresh_saved()

    def _guard_settings(self, proceed: Callable[[], None]) -> None:
        editor = self.config_editor
        if self.current_mode != "settings" or editor is None or not editor.dirty:
            proceed()
            return
        self._prompt_unsaved(proceed)

    def _prompt_unsaved(self, proceed: Callable[[], None]) -> None:
        self.push_screen(
            ConfigPrompt(
                "Save or discard unsaved configuration changes?",
                choices=(("Save", "save"), ("Discard", "discard"), ("Stay", "stay")),
            ),
            lambda choice: self._resolve_guard(choice, proceed),
        )

    def _resolve_guard(self, choice: str | None, proceed: Callable[[], None]) -> None:
        if choice in {None, "stay"}:
            return
        if choice == "save" and not self.save_config():
            return
        if choice == "discard" and self.config_editor is not None:
            self.config_editor.discard()
        proceed()

    def action_help(self) -> None:
        screen = self.current_hub_screen
        if screen is None or isinstance(self.screen, HelpOverlay):
            return
        if self.screen is screen:
            self.push_screen(HelpOverlay(screen.SCREEN_TITLE, screen.active_bindings))
            return
        # A dialog: its bindings stop at the modal, so the overlay lists its own keys.
        dialog = self.screen
        title = getattr(dialog, "dialog_title", "") or "dialog"
        self.push_screen(HelpOverlay(title, dialog.active_bindings))

    # Drawing

    def refresh_view(self) -> None:
        """Redraw the current screen body, its sidebar and its footer."""
        screen = self.current_hub_screen
        if screen is None or not self.is_running or not screen.ready or not screen.is_attached:
            return
        screen.refresh_body()
        sidebar = screen.query_one(Sidebar)
        sidebar.show_navigation(self.current_mode, self._badges())
        sidebar.show_engine(self.engine_sampler.snapshot())
        title, content, buttons, disabled = self._context_cards.get(
            self.current_mode, ("", "", (), frozenset())
        )
        sidebar.show_context(content, title, buttons, disabled)
        screen.draw_hints()

    def _badges(self) -> dict[str, str | Text]:
        badges: dict[str, str | Text] = {}
        session = getattr(self.services, "session", None)
        if self.services.recording:
            paused = session is not None and session.paused
            elapsed = session.elapsed_seconds if session is not None else 0
            badges["record"] = StatusToken.text(
                "Ⅱ" if paused else "●", Clock.format(elapsed), "warn" if paused else "danger"
            )
        count = self.library_screen.entry_count
        if count is not None:
            badges["library"] = str(count)
        report = self.checks_tab.report
        if report is not None:
            warned, failed = report.warn_count, report.fail_count
            if failed:
                badges["settings"] = Text(f"{failed} F", style=StatusToken.TONES["danger"])
            elif warned:
                badges["settings"] = Text(f"{warned} W", style=StatusToken.TONES["warn"])
        return badges

    def _refresh_live(self) -> None:
        if self.current_mode == "record":
            self.refresh_view()

    def _sample_engine(self) -> None:
        self.engine_sampler.sample()
        self.refresh_view()

    # Shared state

    def current_config(self) -> Config:
        editor = self.config_editor
        if editor is not None and editor.config is not None:
            return editor.config
        return Config.defaults()

    def save_config(self) -> bool:
        editor = self.config_editor
        if editor is None or editor.read_only:
            return False
        try:
            result = editor.save()
        except (ConfigError, ConfigPersistenceError) as exc:
            self.notify(str(exc), severity="error")
            self.refresh_view()
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
        self.refresh_view()
        return True

    def _default_setup_test(self, step_id: str, config: Config) -> str:
        from stenographer.lib.config.paths import resolve_config_path

        config_dir = (
            self.config_editor.path.parent
            if self.config_editor is not None
            else resolve_config_path().parent
        )
        return test_setup_step(step_id, config, config_dir)

    # Quit rules (README §4.1)

    def action_request_quit(self) -> None:
        if self.activity_status is not None:
            return
        editor = self.config_editor
        if editor is not None and editor.dirty:
            self._prompt_unsaved(self.action_request_quit)
            return
        self._continue_quit()

    def _continue_quit(self) -> None:
        recording = self.services.recording
        work = []
        if recording:
            work.append(("recording", "Stop and save the recording."))
        if getattr(self.services, "stopping_sessions", ()):
            work.append(
                ("relabel", "Skip the running relabel; those sessions keep their live labels.")
            )
        if self.library_screen.files_running:
            work.append(("files", "Cancel the running file job."))
        if not work:
            self.exit()
            return
        names = ",".join(name for name, _line in work)
        log.info(fmt_event("hub", "quit_prompted", work=names))
        lines = "\n".join(f"· {line}" for _name, line in work)
        self.push_screen(
            QuitConfirm(
                f"Quit and do this first?\n{lines}",
                confirm="Save and quit" if recording else "Quit",
                cancel="Keep recording" if recording else "Cancel",
                quit_keys=True,
            ),
            lambda confirmed: self._confirm_quit(names, confirmed),
        )

    def _confirm_quit(self, work: str, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "quit_confirmed", work=work, confirmed=bool(confirmed)))
        if confirmed:
            self._switch("record")
            self.run_worker(self._finish_work_and_quit(), name="quit-work", group="hub-work")

    def _show_quit_status(self, status: str) -> None:
        self.activity_status = status
        self.refresh_view()

    async def _finish_work_and_quit(self) -> None:
        services = self.services
        if services.recording:
            self._show_quit_status("Saving recording...")
            try:
                await asyncio.to_thread(services.stop_recording)
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: recording_stop_failed", exc, safe=True)
                self._quit_step_failed(f"Could not save the recording: {exc}")
                return
        if getattr(services, "stopping_sessions", ()):
            # Each stop still finishes writing its files; only the relabel passes end early.
            self._show_quit_status("Saving recordings...")
            await asyncio.to_thread(services.skip_relabels)
            await asyncio.to_thread(services.wait_for_stops)
        if self.library_screen.files_running:
            self._show_quit_status("Canceling the file job...")
            try:
                await asyncio.to_thread(services.cancel_files)
            except Exception as exc:
                log_failure(log, logging.ERROR, "hub: files_cancel_failed", exc, safe=True)
                self._quit_step_failed(f"Could not cancel the file job: {exc}")
                return
        self.activity_status = None
        self.exit()

    def _quit_step_failed(self, message: str) -> None:
        self.notify(message, severity="error")
        self.activity_status = None
        self.refresh_view()
