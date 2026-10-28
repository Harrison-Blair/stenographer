# SPDX-License-Identifier: GPL-3.0-or-later
"""The Quick setup dialog of the Checks tab: input access, microphone and hotkey."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.doctor_view import DOCTOR_STATE_GLYPHS, DOCTOR_STATE_TONES
from stenographer.cli.hub.widgets.dialog import Dialog
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.logging.pipeline import fmt_event, log_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult

    from stenographer.cli.hub.doctor_view import DoctorReport
    from stenographer.lib.config.models import Config

log = logging.getLogger(__name__)

# The three quick setup steps: (test area, name, check, setting row, description).
QUICK_STEPS = (
    (
        "input_access",
        "input access",
        "key_injector_ok",
        None,
        "Check keyboard injection and global hotkey access.",
    ),
    (
        "microphone",
        "microphone",
        "has_mic",
        "audio.input_device",
        "Select an input device. The test only lists devices; it does not capture audio.",
    ),
    (
        "hotkey",
        "hotkey",
        "hotkey_access_ok",
        "hotkey.binding",
        "Set the push-to-talk binding. The test validates the binding and input access.",
    ),
)


class QuickSetupDialog(Dialog[str]):
    """Test each quick setup step; ``e`` closes with the setting row to edit."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        ("up", "move(-1)", "Previous step"),
        ("down", "move(1)", "Next step"),
        ("t", "test", "Test the selected step"),
        ("e", "edit", "Edit the setting of the selected step"),
    ]

    def __init__(
        self,
        config: Config,
        report: DoctorReport | None,
        setup_test: Callable[[str, Config], str],
    ) -> None:
        super().__init__("Quick setup")
        self.config = config
        self.report = report
        self._setup_test = setup_test
        self.index = 0
        self.results: dict[str, str] = {}

    def compose_body(self) -> ComposeResult:
        yield SelectableList(id="quick-setup-steps")
        yield Static("", id="quick-setup-detail", markup=False)

    def buttons(self) -> tuple[tuple[str, str, str], ...]:
        return (("esc", "Close", "cancel"), ("t", "Test", "test"), ("e", "Edit…", "edit"))

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        checks = {check.check_id: check for check in self.report.checks} if self.report else {}
        rows = []
        for area, name, check_id, _key, _text in QUICK_STEPS:
            check = checks.get(check_id)
            row = Text()
            if check is None:
                row.append("○", style=StatusToken.TONES["dim"])
            else:
                row.append(
                    DOCTOR_STATE_GLYPHS[check.status],
                    style=StatusToken.TONES[DOCTOR_STATE_TONES[check.status]],
                )
            row.append(f" {name:<14} {self._current_value(area, check)}")
            rows.append((row, ""))
        self.query_one("#quick-setup-steps", SelectableList).set_rows(tuple(rows), self.index)
        area, _name, _check, key, description = QUICK_STEPS[self.index]
        detail = description
        if key is not None:
            detail += f"\nsetting: {key}"
        detail += f"\ntest: {self.results.get(area, 'not run')}"
        self.query_one("#quick-setup-detail", Static).update(detail)

    def _current_value(self, area: str, check) -> str:
        if area == "microphone":
            return self.config.audio.input_device or "automatic"
        if area == "hotkey":
            return f"{self.config.hotkey.binding} · {self.config.hotkey.mode}"
        return check.detail if check is not None else "not checked"

    def on_row_selected(self, event) -> None:
        event.stop()
        self.index = event.index
        self.refresh_view()

    def action_move(self, offset: int) -> None:
        self.index = (self.index + offset) % len(QUICK_STEPS)
        self.refresh_view()

    def action_test(self) -> None:
        area = QUICK_STEPS[self.index][0]
        self.results[area] = "running…"
        self.refresh_view()
        self.run_worker(self._run_test(area), group="quick-setup-test")

    async def _run_test(self, area: str) -> None:
        log.info(fmt_event("hub", "setup_test_started", step=area))
        try:
            result = await asyncio.to_thread(self._setup_test, area, self.config)
        except Exception as exc:
            log_failure(log, logging.ERROR, "hub: setup_test_failed", exc, safe=False, step=area)
            result = f"failed: {type(exc).__name__}"
        else:
            log.info(fmt_event("hub", "setup_test_completed", step=area))
        self.results[area] = result
        self.refresh_view()

    def action_edit(self) -> None:
        _area, name, _check, key, _text = QUICK_STEPS[self.index]
        if key is None:
            self.app.notify(f"No setting edits {name}; it is a system permission.")
            return
        self.dismiss(key)
