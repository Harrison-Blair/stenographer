# SPDX-License-Identifier: GPL-3.0-or-later
"""A horizontal bar of speakers and warnings that wraps between items."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from stenographer.cli.hub.widgets.update_changed import update_changed

_GAP = "   "
_DIM = "#8b93a1"


class SpeakerBar(Static):
    """Show items on as few rows as fit; a new row starts only between two items.

    With ``one_row``, the first ``speakers`` items share one row that ends with
    ``+N`` for the speakers that do not fit; the other items wrap below it.
    """

    DEFAULT_CSS = """
    SpeakerBar {
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.items: tuple[Text, ...] = ()
        self.speakers = 0
        self.one_row = False

    def set_items(
        self, items: tuple[Text, ...], *, speakers: int = 0, one_row: bool = False
    ) -> None:
        self.items = items
        self.speakers = speakers
        self.one_row = one_row
        update_changed(self, self.bar_text(self.size.width))

    def on_resize(self) -> None:
        update_changed(self, self.bar_text(self.size.width))

    def bar_text(self, width: int) -> Text:
        """Return the items flowed into ``width`` cells; no width yet gives one row."""
        if not (self.one_row and self.speakers and width):
            return self._flow(self.items, width)
        speakers, rest = self.items[: self.speakers], self.items[self.speakers :]
        text = self._speaker_row(speakers, width)
        if rest:
            text.append("\n")
            text.append_text(self._flow(rest, width))
        return text

    @staticmethod
    def _speaker_row(speakers: tuple[Text, ...], width: int) -> Text:
        """Return as many speakers as fit in one row, then ``+N`` for the others."""
        for shown in range(len(speakers), 0, -1):
            hidden = len(speakers) - shown
            more = [Text(f"+{hidden}", style=_DIM)] if hidden else []
            row = Text(_GAP).join([*speakers[:shown], *more])
            if row.cell_len <= width:
                return row
        return Text(f"+{len(speakers)}", style=_DIM)

    @staticmethod
    def _flow(items: tuple[Text, ...], width: int) -> Text:
        text = Text()
        used = 0
        for item in items:
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
