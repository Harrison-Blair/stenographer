# SPDX-License-Identifier: GPL-3.0-or-later
"""The one bordered box of the hub."""

from __future__ import annotations

from textual.containers import Vertical


class Frame(Vertical):
    """A rounded box with a dim title; variants set the border colour."""

    DEFAULT_CSS = """
    Frame {
        height: auto;
        padding: 0 1;
        border: round #3a4150;
        border-title-color: #8b93a1;
        overflow: hidden hidden;
    }
    Frame.-mic { border: round #5fd7ff; }
    Frame.-system { border: round #ffaf5f; }
    Frame.-record { border: round #ff875f; }
    Frame.-success { border: round #6ee69a; }
    Frame.-focus { border: round #5fd7ff; }
    Frame.-fill { height: 1fr; }
    """

    def __init__(self, *children, title: str = "", variant: str | None = None, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.border_title = title
        if variant is not None:
            self.add_class(f"-{variant}")
