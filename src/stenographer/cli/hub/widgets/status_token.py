# SPDX-License-Identifier: GPL-3.0-or-later
"""A glyph plus one or two words; colour only adds to the meaning."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.widgets import Static


class StatusToken(Static):
    """Show one state as a glyph and a word in the colour of its tone."""

    TONES: ClassVar[dict[str, str]] = {
        "info": "#5fd7ff",
        "ok": "#6ee69a",
        "warn": "#ffaf5f",
        "danger": "#ff875f",
        "dim": "#8b93a1",
    }
    DEFAULT_CSS = """
    StatusToken {
        width: auto;
        height: 1;
    }
    """

    def __init__(self, glyph: str, word: str, tone: str = "info", **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.set_state(glyph, word, tone)

    def set_state(self, glyph: str, word: str, tone: str = "info") -> None:
        """Show a new state; a state without a glyph or a word is an error."""
        self.update(self.text(glyph, word, tone))

    @classmethod
    def text(cls, glyph: str, word: str, tone: str = "info") -> Text:
        """Return the token as styled text for a row or a card."""
        if not glyph.strip() or not word.strip():
            raise ValueError("a status token needs a glyph and a word")
        return Text(f"{glyph} {word}", style=cls.TONES[tone], no_wrap=True)
