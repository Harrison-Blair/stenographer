# SPDX-License-Identifier: GPL-3.0-or-later
"""The Checks tab of Settings: system checks, their fixes and tests, and the setup dialogs."""

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
from stenographer.cli.hub.defaults_dialog import DefaultsDialog
from stenographer.cli.hub.doctor_panel import DoctorPanel
from stenographer.cli.hub.doctor_view import (
    DOCTOR_STATE_GLYPHS,
    DOCTOR_STATE_TONES,
    DOCTOR_STATE_WORDS,
    DoctorCheck,
    DoctorReport,
)
from stenographer.cli.hub.models_dialog import ModelsDialog
from stenographer.cli.hub.quick_setup_dialog import QuickSetupDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.config.errors import ConfigError, ConfigPersistenceError
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.doctor_view import ModelEntry
    from stenographer.cli.hub.widgets.row_selected import RowSelected
    from stenographer.lib.config.models import Config

log = logging.getLogger(__name__)

# The fix of a check: its button text and a dotted setting key or a dialog.
_FIXES = {
    "key_injector_ok": ("run quick setup", "quick_setup"),
    "has_mic": ("choose a microphone", "audio.input_device"),
    "hotkey_access_ok": ("set the hotkey", "hotkey.binding"),
    "cue_player": ("choose a sound pack", "feedback.sound_pack"),
    "model_cached": ("download the model", "models"),
    "live_models_cached": ("download the models", "models"),
    "refine_service": ("set the refine host", "refine.host"),
    "overlay": ("overlay setting", "feedback.overlay"),
    "clipboard_restore": ("clipboard restore setting", "delivery.restore_clipboard"),
}
# The test of a check: its button text and the setup test area.
_TESTS = {
    "key_injector_ok": ("check access", "input_access"),
    "has_mic": ("list devices", "microphone"),
    "hotkey_access_ok": ("check binding", "hotkey"),
    "cue_player": ("play cues", "sounds"),
    "model_cached": ("model files", "models"),
    "live_models_cached": ("model files", "models"),
    "system_service": ("service state", "system_service"),
}


class ChecksTab(Vertical):
    """Run the system checks; fix and test the selected check; open the setup dialogs.

    The Settings screen focuses this tab while it shows, so its bindings come
    before the bindings of the config tabs.
    """

    can_focus = True
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move_check(-1)", "Previous check"),
        ("down", "move_check(1)", "Next check"),
        ("enter", "toggle_details", "Show or hide how to fix the check"),
        ("r", "run_checks", "Run the checks again"),
        ("f", "fix", "Fix the selected check"),
        ("t", "test", "Test the area of the selected check"),
        ("l", "open_log", "Open the log"),
        ("c", "copy_report", "Copy the check report"),
        Binding("shift+q", "quick_setup", "Quick setup", key_display="Q"),
        ("m", "models", "Show and download the models"),
        Binding("shift+d", "defaults", "Write the default configuration", key_display="D"),
    ]
    DEFAULT_CSS = """
    ChecksTab {
        height: 1fr;
    }
    ChecksTab:focus {
        background-tint: transparent;
    }
    ChecksTab #checks-body {
        height: 1fr;
        padding: 1 1 0 1;
        border: round #3a4150;
    }
    ChecksTab #checks-list-column {
        width: 48;
        height: 1fr;
        margin-right: 2;
    }
    ChecksTab #checks-list-hint {
        height: 1;
        color: #8b93a1;
    }
    ChecksTab #checks-run {
        margin-top: 1;
    }
    ChecksTab #checks-detail {
        width: 1fr;
    }
    ChecksTab #checks-detail-head {
        text-style: bold;
    }
    ChecksTab #checks-detail-path {
        color: #8b93a1;
    }
    ChecksTab #checks-detail-buttons, ChecksTab #checks-dialog-buttons {
        height: 1;
        margin-top: 1;
    }
    ChecksTab #checks-report-buttons {
        height: 1;
    }
    ChecksTab #checks-warnings-title {
        height: 2;
        margin-top: 1;
        border-top: solid #3a4150;
        color: #8b93a1;
        text-style: bold;
    }
    ChecksTab #checks-warnings {
        height: 1fr;
        overflow-y: auto;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def __init__(
        self,
        *,
        doctor_probe: Callable[[Config, pathlib.Path | None], DoctorReport],
        setup_test: Callable[[str, Config], str],
        model_download: Callable[[str], None],
        model_status: Callable[[], tuple[ModelEntry, ...]],
        open_log: Callable[[pathlib.Path], bool],
        copy_report: Callable[[str], None] | None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._doctor_probe = doctor_probe
        self._setup_test = setup_test
        self._model_download = model_download
        self._model_status = model_status
        self._open_log = open_log
        self._copy_report = copy_report
        self.doctor_panel = DoctorPanel(id="doctor-panel")
        self.report: DoctorReport | None = None
        self.checking = False
        self.index = 0
        self.details = False
        self.ran_at: datetime.datetime | None = None
        self.test_status = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="checks-body"):
            with Vertical(id="checks-list-column"):
                yield self.doctor_panel
                yield Static("↑↓ check · enter details · t test", id="checks-list-hint")
                yield HubButton("Run again", key="r", action="run_checks", id="checks-run")
            with Frame(id="checks-detail", variant="fill"):
                yield Static("", id="checks-detail-head", markup=False)
                yield Static("", id="checks-detail-body", markup=False)
                yield Static("", id="checks-detail-path", markup=False)
                with Horizontal(id="checks-detail-buttons"):
                    yield HubButton("Fix", key="f", action="fix", id="checks-fix", tone="primary")
                    yield HubButton("Test", key="t", action="test", id="checks-test")
                with Horizontal(id="checks-report-buttons"):
                    yield HubButton("Open log", key="l", action="open_log", id="checks-log")
                    yield HubButton("Copy report", key="c", action="copy_report", id="checks-copy")
                yield Static("", id="checks-test-status", markup=False)
                yield Static(
                    "recent warnings (no transcript text)",
                    id="checks-warnings-title",
                    markup=False,
                )
                yield Static("", id="checks-warnings", markup=False)
                with Horizontal(id="checks-dialog-buttons"):
                    yield HubButton(
                        "Quick setup…", key="Q", action="quick_setup", id="checks-quick"
                    )
                    yield HubButton("Models…", key="m", action="models", id="checks-models")
                    yield HubButton("Defaults…", key="D", action="defaults", id="checks-defaults")

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
        card = Text()
        counts = (
            (report.ok_count, "pass", "ok"),
            (report.warn_count, "warn", "warn"),
            (report.fail_count, "fail", "danger"),
        )
        for position, (count, word, tone) in enumerate(counts):
            if position:
                card.append(" · ")
            card.append(f"{count} {word}", style=StatusToken.TONES[tone] if count else None)
        card.append(f"\nlast run {ran_at}\n[r] Run again")
        return card

    def refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self.doctor_panel.refresh_view(
            self.report, selected_index=self.index, loading=self.checking
        )
        check = self.selected
        head = self.query_one("#checks-detail-head", Static)
        body = self.query_one("#checks-detail-body", Static)
        path = self.query_one("#checks-detail-path", Static)
        fix = self.query_one("#checks-fix", HubButton)
        test = self.query_one("#checks-test", HubButton)
        if check is None:
            head.update("Checking system capabilities…" if self.checking else "No check selected.")
            body.update("")
            path.update("")
            fix.display = test.display = False
        else:
            title = Text()
            title.append(
                DOCTOR_STATE_GLYPHS[check.status],
                style=StatusToken.TONES[DOCTOR_STATE_TONES[check.status]],
            )
            title.append(f" {check.label} · {DOCTOR_STATE_WORDS[check.status]}")
            head.update(title)
            lines = [line for line in (check.explanation, check.detail) if line]
            if self.details and check.fix:
                lines.append(f"how to fix: {check.fix}")
            body.update("\n".join(lines))
            checked = f"checked {self.report.checked_at:%H:%M}"
            path.update(f"{checked} · {check.path}" if check.path else checked)
            fix_entry = _FIXES.get(check.check_id)
            fix.display = fix_entry is not None and check.status != "ok"
            if fix_entry is not None:
                fix.set_label(f"Fix: {fix_entry[0]}")
            test_entry = _TESTS.get(check.check_id)
            test.display = test_entry is not None
            if test_entry is not None:
                test.set_label(f"Test: {test_entry[0]}")
        status = self.query_one("#checks-test-status", Static)
        status.update(f"test: {self.test_status}" if self.test_status else "")
        self.query_one("#checks-warnings", Static).update(self._warnings_text())

    def _warnings_text(self) -> Text:
        entries = self.report.warning_entries() if self.report is not None else ()
        if not entries:
            return Text("No recent warnings.", style=StatusToken.TONES["dim"])
        text = Text()
        for time, level, token, description in entries:
            if text:
                text.append("\n")
            text.append(f"{time}  ", style=StatusToken.TONES["dim"])
            text.append(
                f"{level:<5}", style=StatusToken.TONES["warn" if level == "WARN" else "danger"]
            )
            text.append(f"  {token}")
            if description:
                text.append(f"\n{'':7}{description}", style=StatusToken.TONES["dim"])
        return text

    def run_checks(self) -> None:
        """Start a check run in a worker of the app; the probe runs in a thread."""
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
                        "other",
                        "fail",
                        type(exc).__name__,
                        "Check the application log for details.",
                    ),
                ),
                (),
            )
        report = report.in_group_order()
        self.report = report
        self.ran_at = datetime.datetime.now()
        log.info(
            fmt_event(
                "hub", "doctor_checked", warn_count=report.warn_count, fail_count=report.fail_count
            )
        )
        self.index = report.first_issue_index
        self.details = False
        self.test_status = ""
        self.checking = False
        app.set_check_summary(report.ok_count, report.warn_count, report.fail_count, self.ran_at)

    def select_check(self, check_id: str) -> None:
        """Select the check with ``check_id``."""
        report = self.report
        if report is None:
            return
        for index, check in enumerate(report.checks):
            if check.check_id == check_id:
                self._select(index)
                return

    def _select(self, index: int) -> None:
        self.index = index
        self.details = False
        self.test_status = ""
        log.info(
            fmt_event("hub", "doctor_check_selected", check=self.report.checks[index].check_id)
        )
        self.app.refresh_view()

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control is self.doctor_panel:
            event.stop()
            self._select(event.index)

    def action_run_checks(self) -> None:
        log.info(fmt_event("hub", "doctor_recheck_requested"))
        self.run_checks()

    def action_move_check(self, offset: int) -> None:
        report = self.report
        if report is None or not report.checks:
            return
        self._select((self.index + offset) % len(report.checks))

    def action_toggle_details(self) -> None:
        self.details = not self.details
        log.info(fmt_event("hub", "doctor_details_toggled", expanded=self.details))
        self.app.refresh_view()

    def action_fix(self) -> None:
        check = self.selected
        if check is None:
            return
        if check.status == "ok":
            log.info(fmt_event("hub", "doctor_fix_not_needed", check=check.check_id))
            self.app.notify("This check does not need a fix.")
            return
        log.info(fmt_event("hub", "doctor_fix_selected", check=check.check_id))
        target = _FIXES.get(check.check_id, (None, None))[1]
        if target is None:
            self.app.notify(check.fix or "No setting fixes this check.")
        elif target == "quick_setup":
            self.action_quick_setup()
        elif target == "models":
            self.action_models()
        else:
            self.app.open_setting(target)

    def action_test(self) -> None:
        check = self.selected
        entry = _TESTS.get(check.check_id) if check is not None else None
        if entry is None:
            self.app.notify("This check has no test.")
            return
        self.test_status = "running…"
        self.app.refresh_view()
        self.app.run_worker(self._run_test(entry[1]), group="setup-test", exclusive=True)

    async def _run_test(self, area: str) -> None:
        log.info(fmt_event("hub", "setup_test_started", step=area))
        try:
            result = await asyncio.to_thread(self._setup_test, area, self.app.current_config())
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_test_failed", exc, safe=False, step=area)
            self.test_status = f"failed: {type(exc).__name__}"
            self.app.notify("The setup test failed; see the log.", severity="error")
        else:
            self.test_status = result
            log.info(fmt_event("hub", "setup_test_completed", step=area))
        self.app.refresh_view()

    def action_open_log(self) -> None:
        from stenographer.lib.logging.pipeline import log_paths

        log.info(fmt_event("hub", "doctor_log_open_requested"))
        try:
            opened = self._open_log(log_paths()[0])
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
            self.app.notify("Could not copy the checks report.", severity="error")
            return
        log.info(fmt_event("hub", "doctor_report_copied"))
        self.app.notify("Checks report copied.")

    def action_quick_setup(self) -> None:
        log.info(fmt_event("hub", "quick_setup_opened"))
        self.app.push_screen(
            QuickSetupDialog(self.app.current_config(), self.report, self._setup_test),
            self._quick_setup_closed,
        )

    def _quick_setup_closed(self, key: str | None) -> None:
        if key is not None:
            self.app.open_setting(key)

    def action_models(self) -> None:
        log.info(fmt_event("hub", "models_opened"))
        self.app.push_screen(ModelsDialog(self._model_status, self._model_download))

    def action_defaults(self) -> None:
        from stenographer.lib.config.paths import resolve_config_path

        app = self.app
        path = app.config_editor.path if app.config_editor is not None else resolve_config_path()
        log.info(fmt_event("hub", "setup_defaults_requested"))
        app.push_screen(
            DefaultsDialog(path), lambda confirmed: self._defaults_closed(path, confirmed)
        )

    def _defaults_closed(self, path: pathlib.Path, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "setup_defaults_confirmed", confirmed=bool(confirmed)))
        if confirmed:
            self.app.run_worker(self._write_defaults(path), group="setup", exclusive=True)

    async def _write_defaults(self, path: pathlib.Path) -> None:
        from stenographer.cli.setup.workflow import save_defaults

        app = self.app
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
