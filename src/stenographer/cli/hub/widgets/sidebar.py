# SPDX-License-Identifier: GPL-3.0-or-later
"""The sidebar of every screen: navigation, engine card and context card."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from stenographer.cli.hub.widgets.engine_card import EngineCard
from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.selectable_list import SelectableList

if TYPE_CHECKING:
    from rich.console import RenderableType

    from stenographer.cli.hub.engine_status import EngineStatus


class Sidebar(Vertical):
    """Show the navigation rows with badges, the engine card and one context card."""

    DEFAULT_CSS = """
    Sidebar {
        width: 30;
        height: 1fr;
        margin-right: 1;
    }
    Sidebar #sidebar-title {
        border-title-color: #5fd7ff;
        border-title-style: bold;
    }
    Sidebar #sidebar-context {
        height: 1fr;
    }
    Sidebar #sidebar-card {
        height: auto;
    }
    """
    SCREENS = (("record", "Record"), ("library", "Library"), ("settings", "Settings"))

    def compose(self) -> ComposeResult:
        with Frame(title="stenographer", id="sidebar-title"):
            yield SelectableList(id="sidebar")
        yield EngineCard(id="engine-card")
        with Frame(id="sidebar-context"):
            yield Static("", id="sidebar-card", markup=False)

    def show_navigation(self, current: str, badges: dict[str, str | Text]) -> None:
        """Show ``1 Record`` to ``3 Settings`` with badges; select ``current``."""
        rows = tuple(
            (f"{index} {label}", badges.get(name, ""))
            for index, (name, label) in enumerate(self.SCREENS, start=1)
        )
        selected = next(i for i, (name, _label) in enumerate(self.SCREENS) if name == current)
        self.query_one("#sidebar", SelectableList).set_rows(rows, selected)

    def show_engine(self, status: EngineStatus) -> None:
        self.query_one("#engine-card", EngineCard).show(status)

    def show_context(self, content: RenderableType, title: str = "") -> None:
        self.query_one("#sidebar-context", Frame).border_title = title
        self.query_one("#sidebar-card", Static).update(content)
