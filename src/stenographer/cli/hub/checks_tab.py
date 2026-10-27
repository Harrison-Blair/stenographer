# SPDX-License-Identifier: GPL-3.0-or-later
"""The Checks tab of Settings: system checks and the setup actions."""

from __future__ import annotations

import asyncio
import datetime
import logging
import pathlib
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_panel import DoctorPanel
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.lib.config.models import Config

log = logging.getLogger(__name__)

# The setting row that Fix opens for a check.
_FIX_SETTINGS = {
    "key_injector_ok": "hotkey.binding",
    "hotkey_access_ok": "hotkey.binding",
    "has_mic": "audio.input_device",
    "system_capture": "audio.input_device",
    "cue_player": "feedback.sound_pack",
}
# The setup test area of a check.
_TEST_AREAS = {
    "key_injector_ok": "input_access",
    "hotkey_access_ok": "input_access",
    "has_mic": "microphone",
    "system_capture": "microphone",
    "model_cached": "models",
    "live_models_cached": "models",
    "cue_player": "sounds",
    "system_service": "system_service",
}
_MODEL_CHECKS = frozenset({"model_cached", "live_models_cached", "ffmpeg", "python_venv"})


class ChecksTab(Vertical):
    """Run the system checks; test, fix and download from the selected check.

    The Settings screen focuses this tab while it shows, so its bindings come
    before the bindings of the config tabs.
    """

    can_focus = True
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move_check(-1)", "Previous check"),
        ("down", "move_check(1)", "Next check"),
        ("enter", "toggle_details", "Show or hide the check details"),
        ("r", "run_checks", "Run the checks again"),
        ("f", "fix", "Fix the selected check"),
        ("t", "test", "Test the area of the selected check"),
        ("l", "open_log", "Open the log"),
        ("c", "copy_report", "Copy the check report"),
        ("m", "download_model", "Download the speech models"),
        Binding("shift+d", "write_defaults", "Write the default configuration", key_display="D"),
    ]
    DEFAULT_CSS = """
    ChecksTab {
        height: 1fr;
    }
    ChecksTab:focus {
        background-tint: transparent;
    }
    ChecksTab #doctor-panel {
        height: 1fr;
    }
    ChecksTab #checks-actions {
        height: 1;
        margin-top: 1;
    }
    ChecksTab #checks-test-status {
        height: auto;
    }
    """

    def __init__(
        self,
        *,
        doctor_probe: Callable[[Config, pathlib.Path | None], DoctorReport],
        setup_test: Callable[[str, Config], str],
        model_download: Callable[[str], None],
        open_log: Callable[[], bool],
        copy_report: Callable[[str], None] | None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._doctor_probe = doctor_probe
        self._setup_test = setup_test
        self._model_download = model_download
        self._open_log = open_log
        self._copy_report = copy_report
        self.doctor_panel = DoctorPanel(id="doctor-panel")
        self.report: DoctorReport | None = None
        self.checking = False
        self.index = 0
        self.details = False
        self.ran_at: datetime.datetime | None = None
        self.test_status = ""
        self._pending_model: str | None = None

    def compose(self) -> ComposeResult:
        yield self.doctor_panel
        with Horizontal(id="checks-actions"):
            yield HubButton("Run again", key="r", action="run_checks")
            yield HubButton("Fix", key="f", action="fix")
            yield HubButton("Test", key="t", action="test")
            yield HubButton("Open log", key="l", action="open_log")
            yield HubButton("Copy report", key="c", action="copy_report")
            yield HubButton("Models…", key="m", action="download_model")
            yield HubButton("Defaults", key="D", action="write_defaults")
        yield Static("", id="checks-test-status", markup=False)

    @property
    def selected(self) -> DoctorCheck | None:
        report = self.report
        if report is None or not 0 <= self.index < len(report.checks):
            return None
        return report.checks[self.index]

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        return (
            ("↑↓", "check"),
            ("enter", "details"),
            ("t", "test"),
            ("f", "fix"),
            ("r", "run again"),
            ("l", "log"),
            ("c", "copy"),
        )

    def summary_card(self) -> Text:
        report = self.report
        if report is None:
            return Text("Checking…" if self.checking else "No check run yet.\n[r] Run again")
        ran_at = self.ran_at.strftime("%H:%M") if self.ran_at is not None else "—"
        return Text(
            f"{report.ok_count} pass · {report.warn_count} warn · {report.fail_count} fail\n"
            f"last run {ran_at}\n[r] Run again"
        )

    def refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self.doctor_panel.refresh_view(
            self.report, selected_index=self.index, details=self.details, loading=self.checking
        )
        status = self.query_one("#checks-test-status", Static)
        status.update(f"test: {self.test_status}" if self.test_status else "")

    def run_checks(self) -> None:
        """Start a check run in a worker of the app."""
        self.checking = True
        self.app.refresh_view()
        self.app.run_worker(self._load_report(), group="doctor", exclusive=True)

    async def _load_report(self) -> None:
        app = self.app
        try:
            report = await asyncio.to_thread(
                self._doctor_probe,
                app.current_config(),
                app.config_editor.path if app.config_editor is not None else None,
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
        self.report = report
        self.ran_at = datetime.datetime.now()
        log.info(
            fmt_event(
                "hub", "doctor_checked", warn_count=report.warn_count, fail_count=report.fail_count
            )
        )
        self.index = report.first_issue_index
        self.details = False
        self.checking = False
        app.set_check_summary(report.ok_count, report.warn_count, report.fail_count, self.ran_at)

    def action_run_checks(self) -> None:
        log.info(fmt_event("hub", "doctor_recheck_requested"))
        self.run_checks()

    def action_move_check(self, offset: int) -> None:
        report = self.report
        if report is None or not report.checks:
            return
        self.index = (self.index + offset) % len(report.checks)
        self.details = False
        log.info(
            fmt_event("hub", "doctor_check_selected", check=report.checks[self.index].check_id)
        )
        self.app.refresh_view()

    def action_toggle_details(self) -> None:
        self.details = not self.details
        log.info(fmt_event("hub", "doctor_details_toggled", expanded=self.details))
        self.app.refresh_view()

    def action_fix(self) -> None:
        check = self.selected
        if check is None:
            return
        if check.status not in {"warn", "fail"}:
            log.info(fmt_event("hub", "doctor_fix_not_needed", check=check.check_id))
            self.app.notify("This check does not need a fix.")
            return
        log.info(fmt_event("hub", "doctor_fix_selected", check=check.check_id))
        if check.check_id in _MODEL_CHECKS:
            self.action_download_model()
        elif check.check_id in _FIX_SETTINGS:
            self.app.open_setting(_FIX_SETTINGS[check.check_id])
        else:
            self.app.notify(check.fix or "No setting fixes this check.")

    async def action_test(self) -> None:
        check = self.selected
        area = _TEST_AREAS.get(check.check_id) if check is not None else None
        if area is None:
            self.app.notify("This check has no test.")
            return
        log.info(fmt_event("hub", "setup_test_started", step=area))
        try:
            result = await asyncio.to_thread(self._setup_test, area, self.app.current_config())
        except Exception as exc:
            self.test_status = f"failed: {exc}"
            log_failure(log, logging.ERROR, "hub: setup_test_failed", exc, safe=False, step=area)
            self.app.notify(f"Setup test failed: {exc}", severity="error")
        else:
            self.test_status = result
            log.info(fmt_event("hub", "setup_test_completed", step=area))
            self.app.notify(result)
        self.app.refresh_view()

    def action_open_log(self) -> None:
        log.info(fmt_event("hub", "doctor_log_open_requested"))
        try:
            opened = self._open_log()
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: doctor_log_open_failed", exc, safe=False)
            opened = False
        if not opened:
            self.app.notify("The application log is not available.", severity="warning")

    def action_copy_report(self) -> None:
        if self.report is None:
            return
        text = self.report.report_text()
        try:
            if self._copy_report is None:
                self.app.copy_to_clipboard(text)
            else:
                self._copy_report(text)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: doctor_report_copy_failed", exc, safe=False)
            self.app.notify("Could not copy the doctor report.", severity="error")
            return
        log.info(fmt_event("hub", "doctor_report_copied"))
        self.app.notify("Doctor report copied.")

    def action_download_model(self) -> None:
        from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME

        self._pending_model = MODEL_DIRNAME
        log.info(fmt_event("hub", "setup_model_download_prompted"))
        self.app.push_screen(
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
            self.app.notify(f"Model download failed: {exc}", severity="error")
        else:
            log.info(fmt_event("hub", "setup_model_download_completed"))
            self.app.notify(f"Model {model} is cached.")

    def action_write_defaults(self) -> None:
        log.info(fmt_event("hub", "setup_defaults_requested"))
        self.app.run_worker(self._write_defaults(), group="setup", exclusive=True)

    async def _write_defaults(self) -> None:
        from stenographer.cli.setup.workflow import save_defaults
        from stenographer.lib.config.paths import resolve_config_path

        app = self.app
        path = app.config_editor.path if app.config_editor is not None else resolve_config_path()
        try:
            result = await asyncio.to_thread(save_defaults, path)
        except (ConfigError, ConfigPersistenceError) as exc:
            log_failure(log, logging.ERROR, "hub: setup_defaults_failed", exc, safe=True)
            app.notify(str(exc), severity="error")
            return
        app.config_editor = ConfigEditor(path)
        update_config = getattr(app.services, "update_config", None)
        if update_config is not None:
            update_config(app.current_config())
        suffix = f"; backup: {result.backup_path}" if result.backup_path is not None else ""
        log.info(fmt_event("hub", "setup_defaults_written", changed=result.changed))
        app.notify(f"Wrote default configuration to {result.path}{suffix}")
        app.refresh_view()
