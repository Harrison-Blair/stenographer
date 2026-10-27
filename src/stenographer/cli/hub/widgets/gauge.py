# SPDX-License-Identifier: GPL-3.0-or-later
"""One gauge row: label, name, value and an eight-cell bar."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class Gauge(Static):
    """Show a percent with a bar, or a size without one; a dash before a sample."""

    DEFAULT_CSS = """
    Gauge {
        height: 1;
        text-wrap: nowrap;
    }
    """
    CELLS = 8

    def __init__(self, label: str, name: str, *, bar: bool = True, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.gauge_label = label
        self.gauge_name = name
        self.bar = bar
        self.set_percent(None)

    def set_percent(self, percent: float | None) -> None:
        """Show a percent value; ``None`` means not sampled yet."""
        value = "—" if percent is None else f"{percent:.0f}%"
        filled = 0 if percent is None else min(self.CELLS, max(0, int(percent / 100 * self.CELLS)))
        self._show(value, filled)

    def set_bytes(self, size: int | None) -> None:
        """Show a memory size in GB; ``None`` means not sampled yet."""
        self._show("—" if size is None else f"{size / 1024**3:.1f} GB", 0)

    def _show(self, value: str, filled: int) -> None:
        text = Text(no_wrap=True)
        text.append(f"{self.gauge_label:<4}", style="#8b93a1")
        text.append(f"{self.gauge_name:<4}")
        text.append(f"{value:>6}")
        if self.bar:
            text.append(f" ▕{'█' * filled}{'·' * (self.CELLS - filled)}▏", style="#5fd7ff")
        self.update(text)
