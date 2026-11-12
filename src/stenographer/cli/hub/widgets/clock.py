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

    def __init__(self, **kwargs) -> None:
        super().__init__(self.format(0), **kwargs)
        self.add_class("-record")

    def set_seconds(self, seconds: float) -> None:
        text = self.format(seconds)
        if text != self.value:
            self.update(text)

    def set_tone(self, tone: str) -> None:
        if not self.has_class(f"-{tone}"):
            self.remove_class("-record", "-saved")
            self.add_class(f"-{tone}")

    @staticmethod
    def duration(seconds: float) -> str:
        whole = int(seconds)
        hours, remainder = divmod(whole, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    @staticmethod
    def talk_time(seconds: float) -> str:
        """Return ``M:SS`` up to ``99:59``, then ``1h40m``; never wider than 5 cells."""
        whole = int(seconds)
        if whole < 6000:
            return f"{whole // 60}:{whole % 60:02d}"
        return f"{whole // 3600}h{whole % 3600 // 60:02d}m"

    @staticmethod
    def format(seconds: float) -> str:
        whole = int(seconds)
        hours, remainder = divmod(whole, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
