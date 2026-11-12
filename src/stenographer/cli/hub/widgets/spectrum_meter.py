# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw one source meter: full spectrum, short spectrum or one level line, by its height."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from stenographer.cli.hub.widgets.spectrum_meter_model import ROWS, SpectrumMeterModel
from stenographer.overlay.spectrum.analysis import DEFAULT_SPECTRUM_FLOOR_DBFS

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np
    from textual import events

_COLORS = {"mic": "#5fd7ff", "system": "#ffaf5f"}
_DIM = "#8b93a1"
_LINE = "#3a4150"
_OK = "#6ee69a"
_REFRESH_SECONDS = 1 / 20
# Head, 8 band rows, band labels and the level row.
_FULL_HEIGHT = ROWS + 3
# 18 bands with a blank between two bands.
_SPACED_WIDTH = 35
_LINE_LABEL = 8
_LINE_STATE = 8


class SpectrumMeter(Widget):
    """Show the spectrum, level, peak and speech light of one live source.

    The head prints ``[m] MIC`` (or ``[s] SYSTEM``) and, while the mic is
    idle, ``[d] device``. A click on either runs the action of that key on the
    nearest ancestor that defines it, so the click and the key do the same.

    The height sets the form: 11 content rows or more give the full spectrum
    with band labels; fewer give a short spectrum without the labels; one row
    gives one level line with a bar.
    """

    DEFAULT_CSS = """
    SpectrumMeter {
        width: 43;
        height: 13;
        border: round #3a4150;
        padding: 0 1;
    }
    SpectrumMeter.-live.-mic { border: round #5fd7ff; }
    SpectrumMeter.-live.-system { border: round #ffaf5f; }
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
        self.add_class(f"-{source}")

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
        width = max(1, self.content_size.width)
        height = self.content_size.height
        if height == 1:
            return self._line(width)
        model = self.model
        on = model.state == "on"
        color = _COLORS[model.source]
        full = height >= _FULL_HEIGHT
        # The short spectrum leaves [d] device to the status line above it.
        left, right = model.head_for(device_key=full)
        # The room does not depend on the token shown now, so the device does not come and go.
        room = width - model.right_width_for(device_key=full) - 1
        if len(left) > room:
            left = model.head_label
        if len(left) > room:
            left = left[: max(0, room - 1)] + "…"
        text = Text(no_wrap=True, overflow="crop")
        text.append(left, style=f"bold {color}" if on else _DIM)
        if right:
            text.append(" " * (width - len(left) - len(right)))
            text.append(right, style=_OK if model.speech and on else _DIM)
        bars = color if on else _LINE
        for row in model.band_rows(ROWS if full else max(1, height - 2)):
            text.append("\n")
            text.append(row if width >= _SPACED_WIDTH else row[::2], style=bars)
        if full:
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

    def _line(self, width: int) -> Text:
        """Return the one-line form: label, level bar, level and speech light."""
        model = self.model
        on = model.state == "on"
        color = _COLORS[model.source]
        text = Text(no_wrap=True, overflow="crop")
        text.append(f"{model.line_label:<{_LINE_LABEL}}", style=f"bold {color}" if on else _DIM)
        if not on:
            text.append(model.level_text, style=_DIM)
            return text
        tail = f" {model.level_slot} dB "
        bar = max(0, width - _LINE_LABEL - len(tail) - _LINE_STATE)
        filled = round(bar * model.level_fraction)
        text.append("█" * filled, style=color)
        text.append("·" * (bar - filled), style=_LINE)
        text.append(tail)
        text.append(
            f"{'● speech' if model.speech else '○ quiet':<{_LINE_STATE}}",
            style=_OK if model.speech else _DIM,
        )
        return text

    async def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None or offset.y != 0:
            return
        width = self.content_size.width
        left, right = self.model.head_for(device_key=self.content_size.height >= _FULL_HEIGHT)
        if right == "[d] device" and offset.x >= width - len(right):
            action = "choose_device"
        elif offset.x < len(left):
            action = f"toggle_{self.model.source}"
        else:
            return
        event.stop()
        for node in self.ancestors:
            if callable(getattr(node, f"action_{action}", None)):
                await self.app.run_action(action, node)
                return

    def _apply_border(self) -> None:
        self.set_class(self.model.state != "idle", "-live")

    def _refresh_if_fed(self) -> None:
        if self._dirty.is_set():
            self._dirty.clear()
            self.refresh()
