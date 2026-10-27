# SPDX-License-Identifier: GPL-3.0-or-later
"""The sidebar engine card: model, state line, gauges and CPU history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from stenographer.cli.hub.widgets.frame import Frame
from stenographer.cli.hub.widgets.gauge import Gauge
from stenographer.cli.hub.widgets.sparkline import Sparkline
from stenographer.cli.hub.widgets.status_token import StatusToken

if TYPE_CHECKING:
    from stenographer.cli.hub.engine_status import EngineStatus

_STATE_TONES = {"relabeling": "warn", "transcribing": "warn", "ready": "ok", "idle": "dim"}


class EngineCard(Frame):
    """Draw one ``EngineStatus`` snapshot."""

    DEFAULT_CSS = """
    EngineCard #engine-model, EngineCard #engine-state {
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(title="engine", **kwargs)

    def compose(self) -> ComposeResult:
        yield Static("", id="engine-model", markup=False)
        yield Static("", id="engine-state", markup=False)
        yield Gauge("cpu", "app", id="engine-cpu-app")
        yield Gauge("", "all", id="engine-cpu-all")
        yield Gauge("ram", "app", bar=False, id="engine-ram-app")
        yield Sparkline("60 s", maximum=100.0, id="engine-history")

    def show(self, status: EngineStatus) -> None:
        """Update every row from the snapshot."""
        if not self.is_mounted:
            return
        self.query_one("#engine-model", Static).update(status.model)
        self.query_one("#engine-state", Static).update(self.state_text(status.state))
        self.query_one("#engine-cpu-app", Gauge).set_percent(status.cpu_app_percent)
        self.query_one("#engine-cpu-all", Gauge).set_percent(status.cpu_all_percent)
        self.query_one("#engine-ram-app", Gauge).set_bytes(status.ram_app_bytes)
        self.query_one("#engine-history", Sparkline).set_values(status.cpu_history)

    @staticmethod
    def state_text(state: str) -> Text:
        """Colour the leading word of the state line by its tone."""
        word = state.split(" ", 1)[0]
        tone = _STATE_TONES.get(word, "dim")
        text = Text(no_wrap=True)
        text.append(word, style=StatusToken.TONES[tone])
        text.append(state[len(word) :])
        return text
