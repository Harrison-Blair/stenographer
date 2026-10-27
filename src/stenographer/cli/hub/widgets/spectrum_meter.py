# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw one source meter: head, 18 bands x 8 rows, band labels and level row."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from stenographer.cli.hub.widgets.spectrum_meter_model import SpectrumMeterModel
from stenographer.overlay.spectrum.analysis import DEFAULT_SPECTRUM_FLOOR_DBFS

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

_COLORS = {"mic": "#5fd7ff", "system": "#ffaf5f"}
_DIM = "#8b93a1"
_LINE = "#3a4150"
_OK = "#6ee69a"
_REFRESH_SECONDS = 1 / 20


class SpectrumMeter(Widget):
    """Show the spectrum, level, peak and speech light of one live source."""

    DEFAULT_CSS = """
    SpectrumMeter {
        width: 43;
        height: 13;
        border: round #3a4150;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        source: str,
        device: str,
        *,
        floor_dbfs: object = DEFAULT_SPECTRUM_FLOOR_DBFS,
        clock: Callable[[], float] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.model = SpectrumMeterModel(source, device, floor_dbfs=floor_dbfs, clock=clock)
        self._dirty = threading.Event()

    def on_mount(self) -> None:
        self._apply_border()
        self.set_interval(_REFRESH_SECONDS, self._refresh_if_fed)

    def feed(self, samples: np.ndarray) -> None:
        """Analyze one block; safe to call from a listener thread."""
        self.model.feed(samples)
        self._dirty.set()

    def set_state(self, state: str, *, idle_text: str = "") -> None:
        """Show ``on``, ``idle`` or ``off``; *idle_text* is the idle level row."""
        self.model.set_state(state, idle_text=idle_text)
        self._apply_border()
        self.refresh()

    def set_speech(self, speech: bool) -> None:
        self.model.speech = speech
        self.refresh()

    def set_device(self, device: str) -> None:
        self.model.device = device
        self.refresh()

    def render(self) -> Text:
        model = self.model
        on = model.state == "on"
        color = _COLORS[model.source]
        width = max(1, self.content_size.width)
        left, right = model.head
        room = width - len(right) - (1 if right else 0)
        if len(left) > room:
            left = left[: max(0, room - 1)] + "…"
        text = Text(no_wrap=True, overflow="crop")
        text.append(left, style=f"bold {color}" if on else _DIM)
        if right:
            text.append(" " * (width - len(left) - len(right)))
            text.append(right, style=_OK if model.speech and on else _DIM)
        bars = color if on else _LINE
        for row in model.rows:
            text.append("\n")
            text.append(row, style=bars)
        text.append("\n")
        text.append(model.scale, style=_DIM)
        text.append("\n")
        level = model.level_text
        if on and "  peak " in level:
            current, peak = level.split("  peak ")
            text.append(current + "  ")
            text.append("peak", style=_DIM)
            text.append(" " + peak)
        else:
            text.append(level)
        return text

    def _apply_border(self) -> None:
        state = self.model.state
        self.styles.border = ("round", _LINE if state == "idle" else _COLORS[self.model.source])

    def _refresh_if_fed(self) -> None:
        if self._dirty.is_set():
            self._dirty.clear()
            self.refresh()
