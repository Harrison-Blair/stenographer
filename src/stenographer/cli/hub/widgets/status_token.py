# SPDX-License-Identifier: GPL-3.0-or-later
"""A glyph plus one or two words; colour only adds to the meaning."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text


class StatusToken:
    """Show one state as a glyph and a word in the colour of its tone."""

    TONES: ClassVar[dict[str, str]] = {
        "info": "#5fd7ff",
        "ok": "#6ee69a",
        "warn": "#ffaf5f",
        "danger": "#ff875f",
        "dim": "#8b93a1",
    }

    @classmethod
    def text(cls, glyph: str, word: str, tone: str = "info") -> Text:
        """Return the token as styled text for a row or a card."""
        return Text(f"{glyph} {word}", style=cls.TONES[tone], no_wrap=True)
