# SPDX-License-Identifier: GPL-3.0-or-later
"""The grouped check list of the Checks tab: a section and a list per group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Static

from stenographer.cli.hub.doctor_view import (
    CHECK_GROUPS,
    DOCTOR_STATE_GLYPHS,
    DOCTOR_STATE_TONES,
)
from stenographer.cli.hub.widgets.row_selected import RowSelected
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport

_NAME_CELLS = 14


class DoctorPanel(Vertical):
    """Show each check as glyph, name and a cut detail, grouped input, engine, other.

    A click on a row posts ``RowSelected`` from this panel with the index of
    that check in the report.
    """

    DEFAULT_CSS = """
    DoctorPanel {
        height: 1fr;
    }
    DoctorPanel .-section {
        height: 1;
        color: #8b93a1;
        text-style: bold;
    }
    DoctorPanel .-section.-later {
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._indexes: dict[str, tuple[int, ...]] = {}

    def compose(self) -> ComposeResult:
        for position, group in enumerate(CHECK_GROUPS):
            section = Static(group, id=f"checks-section-{group}", markup=False)
            section.add_class("-section")
            if position:
                section.add_class("-later")
            yield section
            yield SelectableList(id=f"checks-{group}")

    def refresh_view(self, report: DoctorReport | None, *, selected_index: int, loading: bool):
        for group in CHECK_GROUPS:
            rows: list[tuple[Text, str]] = []
            indexes: list[int] = []
            if report is not None:
                for index, check in enumerate(report.checks):
                    if check.display_group == group:
                        rows.append((self.row_text(check), ""))
                        indexes.append(index)
            elif group == "input":
                rows.append(
                    (Text("Checking system capabilities…" if loading else "No checks."), "")
                )
            self._indexes[group] = tuple(indexes)
            selected = indexes.index(selected_index) if selected_index in indexes else None
            self.query_one(f"#checks-{group}", SelectableList).set_rows(tuple(rows), selected)
            shown = bool(rows)
            self.query_one(f"#checks-section-{group}").display = shown
            self.query_one(f"#checks-{group}").display = shown

    @staticmethod
    def row_text(check: DoctorCheck) -> Text:
        tone = StatusToken.TONES[DOCTOR_STATE_TONES[check.status]]
        text = Text()
        text.append(DOCTOR_STATE_GLYPHS[check.status], style=tone)
        text.append(f" {check.label:<{_NAME_CELLS}} {check.detail}")
        return text

    def on_row_selected(self, event: RowSelected) -> None:
        if event.control is self:
            return
        event.stop()
        group = event.control.id.removeprefix("checks-")
        indexes = self._indexes.get(group, ())
        if 0 <= event.index < len(indexes):
            self.post_message(RowSelected(self, indexes[event.index]))
