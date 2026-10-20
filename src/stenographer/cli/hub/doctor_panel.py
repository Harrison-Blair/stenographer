# SPDX-License-Identifier: GPL-3.0-or-later
"""Render grouped doctor checks, issue details, and recent warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.selection import append_line

if TYPE_CHECKING:
    from stenographer.cli.hub.doctor_view import DoctorReport


class DoctorPanel(Vertical):
    """Show grouped checks, the selected issue, and recent warnings."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="doctor-groups"):
            yield Static("", id="doctor-input-group", markup=False)
            yield Static("", id="doctor-engine-group", markup=False)
        yield Static("", id="doctor-issue", markup=False)
        yield Static("", id="doctor-warnings", markup=False)

    def refresh_view(
        self,
        report: DoctorReport | None,
        *,
        selected_index: int,
        details: bool,
        loading: bool,
    ) -> None:
        group_names = ("input and audio", "engine and desktop")
        group_ids = ("doctor-input-group", "doctor-engine-group")
        for group, widget_id in zip(group_names, group_ids, strict=True):
            widget = self.query_one(f"#{widget_id}", Static)
            widget.border_title = group
            rows = Text()
            if report is not None:
                for index, check in enumerate(report.checks):
                    if check.group == group:
                        state = {"ok": "✓", "warn": "!", "fail": "x"}[check.status]
                        append_line(
                            rows,
                            f"{state} {check.label} · {check.detail}",
                            selectable=True,
                            selected=index == selected_index,
                        )
            if not rows:
                append_line(rows, "Checking system capabilities…" if loading else "No checks.")
            widget.update(rows)

        issue = self.query_one("#doctor-issue", Static)
        selected = (
            report.checks[selected_index]
            if report is not None and 0 <= selected_index < len(report.checks)
            else None
        )
        issue.border_title = (
            "selected issue" if selected is None else f"selected issue · {selected.label}"
        )
        issue_text = Text()
        if selected is None:
            append_line(
                issue_text, "Checking system capabilities…" if loading else "No issue selected."
            )
        elif selected.status in {"warn", "fail"}:
            append_line(issue_text, f"{selected.status.upper()} · {selected.label}")
            if details:
                append_line(issue_text, f"Detail: {selected.detail}")
                if selected.fix:
                    append_line(issue_text, f"Fix: {selected.fix}")
            else:
                append_line(issue_text, "Press enter for details and fix.")
        else:
            append_line(issue_text, f"{selected.label} · {selected.detail}")
            append_line(issue_text, "No fix required.")
        issue.update(issue_text)

        warnings = self.query_one("#doctor-warnings", Static)
        warnings.border_title = "recent warnings · stenographer.log"
        warning_text = Text()
        if report is not None and report.warnings:
            for warning in report.warnings:
                append_line(warning_text, warning)
        else:
            append_line(warning_text, "No recent warnings.")
        warnings.update(warning_text)
