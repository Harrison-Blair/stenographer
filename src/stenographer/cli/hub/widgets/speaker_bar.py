# SPDX-License-Identifier: GPL-3.0-or-later
"""A horizontal bar of speakers and warnings that wraps between items."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from stenographer.cli.hub.widgets.update_changed import update_changed

_GAP = "   "


class SpeakerBar(Static):
    """Show items on as few rows as fit; a new row starts only between two items."""

    DEFAULT_CSS = """
    SpeakerBar {
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.items: tuple[Text, ...] = ()

    def set_items(self, items: tuple[Text, ...]) -> None:
        self.items = items
        update_changed(self, self.bar_text(self.size.width))

    def on_resize(self) -> None:
        update_changed(self, self.bar_text(self.size.width))

    def bar_text(self, width: int) -> Text:
        """Return the items flowed into ``width`` cells; no width yet gives one row."""
        text = Text()
        used = 0
        for item in self.items:
            if used:
                if width and used + len(_GAP) + item.cell_len > width:
                    text.append("\n")
                    used = 0
                else:
                    text.append(_GAP)
                    used += len(_GAP)
            text.append_text(item)
            used += item.cell_len
        return text
