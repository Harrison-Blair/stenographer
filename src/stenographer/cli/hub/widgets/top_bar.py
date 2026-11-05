# SPDX-License-Identifier: GPL-3.0-or-later
"""The top line of every screen: navigation with badges, then the engine status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Horizontal
from textual.widgets import Static

from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.hub.widgets.update_changed import update_changed

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from stenographer.cli.hub.engine_status import EngineStatus

_ACCENT_BOLD = "bold #5fd7ff"
_DIM = StatusToken.TONES["dim"]
_STATE_TONES = {"relabeling": "warn", "transcribing": "warn", "ready": "ok", "idle": "dim"}


class TopBar(Horizontal):
    """Show one button per screen and one ``EngineStatus`` snapshot; ``▶`` marks the screen."""

    DEFAULT_CSS = """
    TopBar {
        height: 1;
        padding: 0 1;
    }
    TopBar #top-engine {
        width: 1fr;
        text-align: right;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """
    SCREENS = (("record", "Record"), ("library", "Library"), ("settings", "Settings"))

    def compose(self) -> ComposeResult:
        for name, _label in self.SCREENS:
            yield HubButton("", action=f"show_screen('{name}')", tight=True, id=f"nav-{name}")
        yield Static("", id="top-engine", markup=False)

    def show(self, current: str, badges: dict[str, str | Text], status: EngineStatus) -> None:
        """Draw the navigation of screen ``current`` and the engine snapshot."""
        for index, (name, label) in enumerate(self.SCREENS, start=1):
            button = self.query_one(f"#nav-{name}", HubButton)
            text = self.nav_text(f"{index} {label}", badges.get(name, ""), selected=name == current)
            if str(button.label) != text.plain:
                button.set_label(text)
        update_changed(self.query_one("#top-engine", Static), self.engine_text(status))

    @staticmethod
    def nav_text(label: str, badge: str | Text, *, selected: bool) -> Text:
        """Return one navigation label; each other screen keeps two blank cells for ``▶``."""
        text = Text("▶ " if selected else "  ", style=_ACCENT_BOLD if selected else "")
        text.append(label)
        if badge:
            text.append(" ")
            text.append_text(badge if isinstance(badge, Text) else Text(badge))
        return text

    @staticmethod
    def engine_text(status: EngineStatus) -> Text:
        """Return model, state and gauges; a dash shows a gauge before its first sample."""
        word = status.state.split(" ", 1)[0]
        text = Text(f"{status.model} ", no_wrap=True)
        text.append(word, style=StatusToken.TONES[_STATE_TONES[word]])
        text.append(status.state[len(word) :])
        text.append("  cpu ", style=_DIM)
        text.append(_percent(status.cpu_app_percent))
        text.append(" all ", style=_DIM)
        text.append(_percent(status.cpu_all_percent))
        text.append("  ram ", style=_DIM)
        size = status.ram_app_bytes
        text.append("—" if size is None else f"{size / 1024**3:.1f}G")
        return text


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"
