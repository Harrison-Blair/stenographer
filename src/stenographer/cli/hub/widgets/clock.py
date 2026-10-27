# SPDX-License-Identifier: GPL-3.0-or-later
"""The elapsed clock in three-row digits."""

from __future__ import annotations

from textual.widgets import Digits


class Clock(Digits):
    """Show ``HH:MM:SS`` three rows tall; the tone class sets the colour."""

    DEFAULT_CSS = """
    Clock { width: auto; }
    Clock.-record { color: #ff875f; }
    Clock.-saved { color: #6ee69a; }
    """

    def __init__(self, seconds: float = 0, *, tone: str = "record", **kwargs) -> None:
        super().__init__(self.format(seconds), **kwargs)
        self.add_class(f"-{tone}")

    def set_seconds(self, seconds: float) -> None:
        self.update(self.format(seconds))

    def set_tone(self, tone: str) -> None:
        self.remove_class("-record", "-saved")
        self.add_class(f"-{tone}")

    @staticmethod
    def format(seconds: float) -> str:
        whole = max(0, int(seconds))
        hours, remainder = divmod(whole, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
