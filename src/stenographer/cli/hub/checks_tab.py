# SPDX-License-Identifier: GPL-3.0-or-later
"""The Checks tab of Settings: system checks, their fixes and tests, and the setup dialogs."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import threading
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Region
from textual.widgets import Static

from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.defaults_dialog import DefaultsDialog
from stenographer.cli.hub.doctor_view import (
    CHECK_GROUPS,
    DOCTOR_STATE_GLYPHS,
    DOCTOR_STATE_TONES,
    DOCTOR_STATE_WORDS,
    UNREADABLE_LOG,
    DoctorCheck,
    DoctorReport,
)
from stenographer.cli.hub.models_dialog import ModelsDialog
from stenographer.cli.hub.quick_setup_dialog import QuickSetupDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.tier import tier_for
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
    "input_device": ("choose a microphone", "audio.input_device"),
    "hotkey_access_ok": ("set the hotkey", "hotkey.binding"),
    "cue_player": ("choose a sound pack", "feedback.sound_pack"),
    "model_cached": ("download the model", "models"),
    "refine_service": ("set the refine host", "refine.host"),
    "overlay": ("overlay setting", "feedback.overlay"),
    "clipboard_restore": ("clipboard restore setting", "delivery.restore_clipboard"),
}
# The button rows of the detail, and the cells a button adds to its label in each row form.
_BUTTON_ROWS = ("#checks-detail-buttons", "#checks-report-buttons", "#checks-dialog-buttons")
_PADDED_CELLS = 5
_TIGHT_GAP = 2
# Each count of the summary has a slot of this width.
_COUNT_SLOT = 2
# The test of a check: its button text and the setup test area.
_TESTS = {
    "key_injector_ok": ("check access", "input_access"),
    "has_mic": ("list devices", "microphone"),
    "hotkey_access_ok": ("check binding", "hotkey"),
    "cue_player": ("play cues", "sounds"),
    "model_cached": ("model files", "models"),
    "system_service": ("service state", "system_service"),
}


class ChecksSummaryRow(Horizontal):
    """The Checks summary on the Settings tab line: back, counts, last run, Run again.

    It sits outside ChecksTab, so its buttons name the tab as their target.
    """

    def __init__(self, tab: ChecksTab, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tab = tab

    def compose(self) -> ComposeResult:
        back = HubButton(
            "← Checks",
            key="esc",
            action="close_detail",
            tight=True,
            target=self.tab,
            id="checks-back",
        )
        run = HubButton(
            "Run again",
            key="r",
            action="run_checks",
            tight=True,
            target=self.tab,
            id="checks-run-again",
        )
        # Inline: the app rules of HubButton outrank default CSS.
        back.styles.margin = (0, 1, 0, 0)
        run.styles.margin = (0, 0, 0, 2)
        yield back
        yield Static("", id="checks-summary", markup=False)
        yield run


class ChecksTab(Vertical):
    """Run the system checks; fix and test the selected check; open the setup dialogs.

    The Settings screen focuses this tab while it shows, so its bindings come
    before the bindings of the config tabs. The list shrinks with the terminal:
    the medium tier shows the check names only, and the narrow tier shows the
    list alone, with ``enter`` for the detail of the selected check and
    ``escape`` back to the list.
    """

    can_focus = True
    # Unscoped: the tier rules start with the screen class.
    SCOPED_CSS = False
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move_check(-1)", "Previous check"),
        ("down", "move_check(1)", "Next check"),
        ("enter", "open_detail", "Show the detail of the selected check"),
        ("escape", "close_detail", "Back to the check list"),
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
    #checks-summary-row {
        width: 1fr;
        height: 1;
    }
    #checks-summary { width: 1fr; text-wrap: nowrap; }
    ChecksTab #checks-body {
        height: 1fr;
    }
    ChecksTab #checks-list-column {
        width: 48;
        height: 1fr;
        margin-right: 2;
    }
    ChecksTab #doctor-panel { height: 1fr; overflow-y: auto; }
    ChecksTab .-section { height: 1; color: #8b93a1; text-style: bold; }
    ChecksTab .-section.-later { margin-top: 1; }
    ChecksTab #checks-list-hint {
        height: 1;
        color: #8b93a1;
    }
    ChecksTab #checks-detail {
        width: 1fr;
        border-left: solid #3a4150;
        padding-left: 1;
    }
    ChecksTab #checks-detail-scroll { height: 1fr; }
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
        height: auto;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    Screen.-medium ChecksTab #checks-list-column { width: 24; }
    Screen.-narrow ChecksTab #checks-list-column { width: 1fr; margin-right: 0; }
    Screen.-narrow ChecksTab #checks-detail { display: none; }
    Screen.-narrow ChecksTab.-detail #checks-detail {
        display: block;
        border-left: none;
        padding-left: 0;
    }
    Screen.-narrow ChecksTab.-detail #checks-list-column { display: none; }
    """

    def __init__(
        self,
        *,
        doctor_probe: Callable[[Config], DoctorReport],
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
        self._model_download_lock = threading.Lock()
        self._model_status = model_status
        self._open_log = open_log
        self._copy_report = copy_report
        self._indexes: dict[str, tuple[int, ...]] = {}
        self.report: DoctorReport | None = None
        self.checking = False
        self.index = 0
        self._test_statuses: dict[str, str] = {}
        self._view_key = None
        self._row_forms: dict[str, tuple] = {}
        self.detail_open = False
        self.summary_row = ChecksSummaryRow(self, id="checks-summary-row")

    @property
    def test_status(self) -> str:
        check = self.selected
        return self._test_statuses.get(check.check_id, "") if check else ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="checks-body"):
            with Vertical(id="checks-list-column"):
                with Vertical(id="doctor-panel"):
                    for position, group in enumerate(CHECK_GROUPS):
                        section = Static(group, id=f"checks-section-{group}", markup=False)
                        section.add_class("-section")
                        if position:
                            section.add_class("-later")
                        yield section
                        yield SelectableList(id=f"checks-{group}")
                yield Static("↑↓ check · t test", id="checks-list-hint")
            with Vertical(id="checks-detail"):
                with VerticalScroll(id="checks-detail-scroll", can_focus=False):
                    yield Static("", id="checks-detail-head", markup=False)
                    yield Static("", id="checks-detail-body", markup=False)
                    yield Static("", id="checks-detail-path", markup=False)
                    with Horizontal(id="checks-detail-buttons"):
                        yield HubButton(
                            "Fix", key="f", action="fix", id="checks-fix", tone="primary"
                        )
                        yield HubButton("Test", key="t", action="test", id="checks-test")
                    with Horizontal(id="checks-report-buttons"):
                        yield HubButton("Open log", key="l", action="open_log", id="checks-log")
                        yield HubButton(
                            "Copy report", key="c", action="copy_report", id="checks-copy"
                        )
                    yield Static("", id="checks-test-status", markup=False)
                    yield Static("recent warnings", id="checks-warnings-title", markup=False)
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

    @property
    def narrow(self) -> bool:
        return tier_for(self.app.size.width) == "narrow"

    def footer_hints(self) -> tuple[tuple[str, str], ...]:
        if self.narrow and self.detail_open:
            return (
                ("esc", "back"),
                ("f", "fix"),
                ("t", "test"),
                ("l", "log"),
                ("c", "copy report"),
            )
        hints = (
            ("r", "run again"),
            ("f", "fix"),
            ("t", "test"),
            ("l", "log"),
            ("c", "copy report"),
            ("Q", "quick setup"),
            ("m", "models"),
            ("D", "defaults"),
        )
        return (("enter", "detail"), *hints) if self.narrow else hints

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "open_detail":
            return self.narrow and not self.detail_open and self.selected is not None
        if action == "close_detail":
            return self.narrow and self.detail_open
        return True

    def action_open_detail(self) -> None:
        self._show_detail(True)

    def action_close_detail(self) -> None:
        self._show_detail(False)

    def _show_detail(self, shown: bool) -> None:
        self.detail_open = shown
        self.set_class(shown, "-detail")
        self.app.refresh_view()

    def summary_text(self, *, last_run: bool = True) -> Text:
        """Return the counts and, unless ``last_run`` is false, the time of the last run."""
        report = self.report
        if report is None:
            return Text("Checking…" if self.checking else "No check run yet.")
        ran_at = report.checked_at.strftime("%H:%M")
        summary = Text()
        counts = (
            (report.ok_count, "pass", "ok"),
            (report.warn_count, "warn", "warn"),
            (report.fail_count, "fail", "danger"),
        )
        for position, (count, word, tone) in enumerate(counts):
            if position:
                summary.append(" · ")
            summary.append(
                f"{count:>{_COUNT_SLOT}} {word}", style=StatusToken.TONES[tone] if count else None
            )
        if last_run:
            summary.append(f" · last run {ran_at}")
        return summary

    def refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self.call_after_refresh(self._fit_rows)
        width = self.summary_row.content_size.width
        key = (
            self.report,
            self.index,
            self.checking,
            self.test_status,
            self._tier(),
            self.detail_open,
            width,
        )
        if key == self._view_key:
            return
        self._refresh_checks()
        self._refresh_summary(width)
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
            lines = [check.detail] if check.detail else []
            if check.fix:
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
        self._view_key = key

    def _refresh_summary(self, width: int) -> None:
        """Fill the tab line: wide shows Run again; medium shows it when it fits whole.

        The counts always show; the last run shows when it fits whole; narrow shows counts.
        """
        row = self.summary_row
        tier = self._tier()
        back = self.narrow and self.detail_open
        back_button = row.query_one("#checks-back", HubButton)
        back_button.display = back
        # In place of the tabs, the back button starts the line.
        row.styles.padding = (0, 0, 0, 0 if back else 2)
        run = row.query_one("#checks-run-again", HubButton)
        full = self.summary_text()
        # Both buttons are tight: the label and the margin are their whole width.
        run_width = run.label.cell_length + run.styles.margin.left
        if back:
            width -= back_button.label.cell_length + back_button.styles.margin.right
        if tier == "wide":
            run.display = True
        elif tier == "medium":
            run.display = not width or full.cell_len + run_width <= width
        else:
            run.display = False
        room = width - (run_width if run.display else 0)
        fits = tier != "narrow" and (not width or full.cell_len <= room)
        text = full if fits else self.summary_text(last_run=False)
        row.query_one("#checks-summary", Static).update(text)

    def _warnings_text(self) -> Text:
        entries = self.report.warning_entries() if self.report is not None else ()
        unreadable = self.report is not None and UNREADABLE_LOG in self.report.warnings
        if not entries and not unreadable:
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
        if unreadable:
            if text:
                text.append("\n")
            text.append(UNREADABLE_LOG, style=StatusToken.TONES["dim"])
        return text

    def _fit_rows(self) -> None:
        if self._view_key is not None and self._view_key[-1] != self.summary_row.content_size.width:
            # The tab line got its width after the last draw; fit the summary to it.
            self.refresh_view()
        self._fit_button_rows()

    def _fit_button_rows(self) -> None:
        """Give each button row the widest form that fits its width.

        ``padded`` is the usual button row; ``tight`` drops the padding; ``stack`` puts one
        button on each line. Inline styles: the app rules of HubButton outrank this CSS.
        """
        for row_id in _BUTTON_ROWS:
            row = self.query_one(row_id)
            width = row.content_size.width
            buttons = [button for button in row.query(HubButton).results(HubButton)]
            labels = [button.label.cell_length for button in buttons if button.display]
            if not width or not labels:
                continue
            if sum(labels) + _PADDED_CELLS * len(labels) <= width:
                form = "padded"
            elif sum(labels) + _TIGHT_GAP * len(labels) <= width:
                form = "tight"
            else:
                form = "stack"
            # A new label or a shown or hidden button needs new widths in the same form.
            signature = (form, tuple((str(b.label), b.display) for b in buttons))
            if self._row_forms.get(row_id) == signature:
                continue
            self._row_forms[row_id] = signature
            stack = form == "stack"
            row.styles.layout = "vertical" if stack else "horizontal"
            row.styles.height = "auto" if stack else 1
            for button in buttons:
                padded = form == "padded"
                button.styles.padding = None if padded else 0
                button.styles.line_pad = None if padded else 0
                button.styles.width = None if padded else button.label.cell_length
                button.styles.margin = None if padded else (0, _TIGHT_GAP, 0, 0)

    def _tier(self) -> str:
        return tier_for(self.app.size.width)

    def _refresh_checks(self):
        report, selected_index, loading = self.report, self.index, self.checking
        names_only = self._tier() == "medium"
        for group in CHECK_GROUPS:
            rows: list[tuple[Text, str]] = []
            indexes: list[int] = []
            if report is not None:
                for index, check in enumerate(report.checks):
                    if check.group == group:
                        rows.append((self.row_text(check, names_only=names_only), ""))
                        indexes.append(index)
            elif group == "input":
                rows.append(
                    (Text("Checking system capabilities…" if loading else "No checks."), "")
                )
            self._indexes[group] = tuple(indexes)
            selected = indexes.index(selected_index) if selected_index in indexes else None
            rows_list = self.query_one(f"#checks-{group}", SelectableList)
            rows_list.set_rows(tuple(rows), selected)
            if selected is not None:
                self.call_after_refresh(self._show_row, rows_list, selected)
            shown = bool(rows)
            self.query_one(f"#checks-section-{group}").display = shown
            self.query_one(f"#checks-{group}").display = shown

    def _show_row(self, rows_list: SelectableList, row: int) -> None:
        """Scroll the list so the selected row shows."""
        top = rows_list.virtual_region.y + row
        self.query_one("#doctor-panel").scroll_to_region(
            Region(0, top, 1, 1), animate=False, immediate=True
        )

    @staticmethod
    def row_text(check: DoctorCheck, *, names_only: bool = False) -> Text:
        tone = StatusToken.TONES[DOCTOR_STATE_TONES[check.status]]
        text = Text()
        text.append(DOCTOR_STATE_GLYPHS[check.status], style=tone)
        text.append(f" {check.label}" if names_only else f" {check.label:<{14}} {check.detail}")
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
        self.report = report
        log.info(
            fmt_event(
                "hub", "doctor_checked", warn_count=report.warn_count, fail_count=report.fail_count
            )
        )
        self.index = report.first_issue_index
        self.checking = False
        app.refresh_view()

    def _select(self, index: int) -> None:
        self.index = index
        log.info(
            fmt_event("hub", "doctor_check_selected", check=self.report.checks[index].check_id)
        )
        self.app.refresh_view()

    def on_resize(self) -> None:
        self.call_after_refresh(self._fit_rows)

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control.id in {f"checks-{group}" for group in CHECK_GROUPS}:
            event.stop()
            group = event.control.id.removeprefix("checks-")
            indexes = self._indexes[group]
            if 0 <= event.index < len(indexes):
                self._select(indexes[event.index])

    def action_run_checks(self) -> None:
        log.info(fmt_event("hub", "doctor_recheck_requested"))
        self.run_checks()

    def action_move_check(self, offset: int) -> None:
        report = self.report
        if report is None or not report.checks:
            return
        self._select((self.index + offset) % len(report.checks))

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
        if self._test_statuses.get(check.check_id) == "running…":
            return
        self._test_statuses[check.check_id] = "running…"
        self.app.refresh_view()
        self.app.run_worker(self._run_test(check.check_id, entry[1]), group="setup-test")

    async def _run_test(self, check_id: str, area: str) -> None:
        log.info(fmt_event("hub", "setup_test_started", step=area))
        try:
            result = await asyncio.to_thread(self._setup_test, area, self.app.current_config())
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_test_failed", exc, safe=False, step=area)
            self._test_statuses[check_id] = f"failed: {type(exc).__name__}"
            self.app.notify("The setup test failed; see the log.", severity="error")
        else:
            self._test_statuses[check_id] = result
            log.info(fmt_event("hub", "setup_test_completed", step=area))
        self.app.refresh_view()

    def action_open_log(self) -> None:
        log.info(fmt_event("hub", "doctor_log_open_requested"))
        self.app.run_worker(self._open_application_log(), group="open-log")

    async def _open_application_log(self) -> None:
        from stenographer.lib.logging.pipeline import log_paths

        try:
            opened = await asyncio.to_thread(self._open_log, log_paths()[0])
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
        self.app.push_screen(
            ModelsDialog(self._model_status, self._model_download, self._model_download_lock)
        )

    def action_defaults(self) -> None:
        app = self.app
        path = app.config_editor.path
        log.info(fmt_event("hub", "setup_defaults_requested"))
        app.push_screen(
            DefaultsDialog(path, app.config_editor.unsaved_change_count),
            lambda confirmed: self._defaults_closed(path, confirmed),
        )

    def _defaults_closed(self, path: pathlib.Path, confirmed: bool | None) -> None:
        log.info(fmt_event("hub", "setup_defaults_confirmed", confirmed=bool(confirmed)))
        if confirmed:
            self.app.run_worker(self._write_defaults(path), group="setup", exclusive=True)

    async def _write_defaults(self, path: pathlib.Path) -> None:
        from stenographer.lib.config.document import save_defaults

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
