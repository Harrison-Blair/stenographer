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

    With ``max_rows``, the first ``speakers`` items take at most that many rows, and the
    last of them ends with ``+N`` for the speakers that do not fit; the other items (the
    notices) wrap below them.
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
        self.max_rows: int | None = None

    def set_items(
        self, items: tuple[Text, ...], *, speakers: int = 0, max_rows: int | None = None
    ) -> None:
        self.items = items
        self.speakers = speakers
        self.max_rows = max_rows
        update_changed(self, self.bar_text(self.size.width))

    def on_resize(self) -> None:
        update_changed(self, self.bar_text(self.size.width))
        # The layout of this resize measured the old text at the new width; measure the
        # new text, or the row keeps the height of the old one.
        self.call_after_refresh(self.refresh, layout=True)

    def bar_text(self, width: int) -> Text:
        """Return the items flowed into ``width`` cells; no width yet gives one row."""
        if self.max_rows is None or not (self.speakers and width):
            return self._flow(self.items, width)
        speakers, rest = self.items[: self.speakers], self.items[self.speakers :]
        text = self._speaker_rows(speakers, width, self.max_rows)
        if rest:
            text.append("\n")
            text.append_text(self._flow(rest, width))
        return text

    @classmethod
    def _speaker_rows(cls, speakers: tuple[Text, ...], width: int, max_rows: int) -> Text:
        """Return as many speakers as fit in ``max_rows`` rows, then ``+N`` for the others."""
        for shown in range(len(speakers), 0, -1):
            hidden = len(speakers) - shown
            more = (Text(f"+{hidden}", style=_DIM),) if hidden else ()
            rows = cls._flow((*speakers[:shown], *more), width)
            if rows.plain.count("\n") < max_rows:
                return rows
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
