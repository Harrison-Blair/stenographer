# SPDX-License-Identifier: GPL-3.0-or-later
"""One row of eight-step glyphs with a label before it."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from stenographer.cli.hub.widgets.update_changed import update_changed


class Sparkline(Static):
    """Show values as ``▁``-``█`` glyphs, scaled to their peak."""

    DEFAULT_CSS = """
    Sparkline {
        height: 1;
        text-wrap: nowrap;
    }
    """
    GLYPHS = "▁▂▃▄▅▆▇█"

    def __init__(
        self,
        label: str,
        *,
        width: int = 20,
        color: str = "#5fd7ff",
        **kwargs,
    ) -> None:
        super().__init__("", markup=False, **kwargs)
        self.spark_label = label
        self.cells = width
        self.color = color
        self.set_values(())

    def set_values(self, values: tuple[float, ...]) -> None:
        """Show the last ``width`` values; an empty series shows a flat dim row."""
        update_changed(self, self.spark_text(values))

    def spark_text(self, values: tuple[float, ...]) -> Text:
        values = tuple(values)[-self.cells :]
        peak = max(values, default=0.0)
        top = len(self.GLYPHS) - 1
        glyphs = "".join(
            self.GLYPHS[min(top, max(0, int(value / peak * top)))] if peak > 0 else self.GLYPHS[0]
            for value in values
        )
        text = Text(no_wrap=True)
        text.append(f"{self.spark_label} ", style="#8b93a1")
        text.append(glyphs.ljust(self.cells, "·"), style=self.color)
        return text
