# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop tables whose columns use the whole viewport without clipping content."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QSize, QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from stenographer_desktop.theme import TOKENS


def proportional_widths(preferred: Sequence[int], available: int) -> list[int]:
    """Keep natural widths when crowded, otherwise divide the viewport proportionally."""
    widths = [max(1, width) for width in preferred]
    total = sum(widths)
    if not widths or available <= 0 or total >= available:
        return widths

    fitted = [available * width // total for width in widths]
    remainder = available - sum(fitted)
    fractions = sorted(
        range(len(widths)),
        key=lambda column: (-(available * widths[column] % total), column),
    )
    for column in fractions[:remainder]:
        fitted[column] += 1
    return fitted


class ContentWidthTable(QTableWidget):
    """Share spare width by natural column size and retain overflow scrolling."""

    _MINIMUM_VISIBLE_ROWS = 2
    _REMEASURE_EVENTS = frozenset(
        {
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.FontChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.StyleChange,
        }
    )

    def __init__(self, headings: Sequence[str]) -> None:
        super().__init__(0, len(headings))
        self.setHorizontalHeaderLabels(headings)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        rows = self.verticalHeader()
        rows.setMinimumSectionSize(TOKENS.table_row_height)
        rows.setDefaultSectionSize(TOKENS.table_row_height)
        self._preferred_widths: tuple[int, ...] | None = None
        self._remeasure_pending = False
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self._refit_columns)
        self.viewport().installEventFilter(self)

    def set_rows(self, rows: Sequence[Sequence[object]]) -> None:
        """Replace the table contents and measure the new natural column widths."""
        self.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.setItem(row, column, QTableWidgetItem(str(value)))
        self.schedule_refit(remeasure=True)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Reserve a header, scrollbar, and two whole rows for readable table content."""
        hint = super().minimumSizeHint()
        content_height = (
            self.horizontalHeader().sizeHint().height()
            + self._MINIMUM_VISIBLE_ROWS * self.verticalHeader().defaultSectionSize()
            + self.horizontalScrollBar().sizeHint().height()
            + 2 * self.frameWidth()
        )
        return QSize(hint.width(), max(hint.height(), content_height))

    def schedule_refit(self, *, remeasure: bool = False) -> None:
        """Coalesce content and geometry changes into one event-loop fit."""
        self._remeasure_pending = self._remeasure_pending or remeasure
        if not self._refit_timer.isActive():
            self._refit_timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.viewport() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self.schedule_refit()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in self._REMEASURE_EVENTS:
            self.schedule_refit(remeasure=True)

    def _natural_widths(self) -> tuple[int, ...]:
        header = self.horizontalHeader()
        minimum = header.minimumSectionSize()
        return tuple(
            max(minimum, self.sizeHintForColumn(column), header.sectionSizeHint(column))
            for column in range(self.columnCount())
        )

    def _refit_columns(self) -> None:
        remeasure = self._remeasure_pending
        self._remeasure_pending = False
        if remeasure or self._preferred_widths is None:
            self._preferred_widths = self._natural_widths()
        available = self.viewport().width()
        if available <= 0 or not self._preferred_widths:
            return
        for column, width in enumerate(proportional_widths(self._preferred_widths, available)):
            if self.columnWidth(column) != width:
                self.horizontalHeader().resizeSection(column, width)
