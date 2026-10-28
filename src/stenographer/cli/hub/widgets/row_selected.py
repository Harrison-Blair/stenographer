# SPDX-License-Identifier: GPL-3.0-or-later
"""The message of a click on a row of a selectable list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

if TYPE_CHECKING:
    from textual.widget import Widget


class RowSelected(Message):
    """A click selected the row at ``index`` of ``selectable_list``."""

    def __init__(self, selectable_list: Widget, index: int) -> None:
        super().__init__()
        self.selectable_list = selectable_list
        self.index = index

    @property
    def control(self) -> Widget:
        return self.selectable_list
