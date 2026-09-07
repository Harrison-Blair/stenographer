# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessible compact trends using Qt's scalable native painting surface."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from stenographer_desktop.theme import TOKENS


class WordTrend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[dict] = []
        self.setMinimumHeight(160)
        self.setAccessibleName("Recognized words per active day")

    def set_points(self, points: list[dict]) -> None:
        self.points = points
        self.setAccessibleDescription(
            "; ".join(f"{point['date']}: {point['recognized_words']} words" for point in points)
            or "No dictation in this period."
        )
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.palette().text().color())
        if not self.points:
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No dictation in this period"
            )
            return
        metrics = painter.fontMetrics()
        text_height = metrics.height()
        inset = 16
        text_gap = 8
        title_top = 8
        title_baseline = title_top + metrics.ascent()
        labels = QRectF(
            inset,
            self.height() - text_gap - text_height,
            self.width() - 2 * inset,
            text_height,
        )
        plot_top = title_top + text_height + text_gap
        area = QRectF(
            inset,
            plot_top,
            self.width() - 2 * inset,
            labels.top() - text_gap - plot_top,
        )
        maximum = max(1, *(point["recognized_words"] for point in self.points))
        width = area.width() / len(self.points)
        accent = QColor(TOKENS.accent)
        painter.drawText(inset, title_baseline, f"Words per active day  ·  maximum {maximum:,}")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        for index, point in enumerate(self.points):
            height = area.height() * point["recognized_words"] / maximum
            painter.drawRoundedRect(
                QRectF(
                    area.left() + index * width, area.bottom() - height, max(1, width - 3), height
                ),
                2,
                2,
            )
        painter.setPen(self.palette().text().color())
        painter.drawText(labels, Qt.AlignmentFlag.AlignLeft, self.points[0]["date"])
        if len(self.points) > 1:
            painter.drawText(
                labels,
                Qt.AlignmentFlag.AlignRight,
                self.points[-1]["date"],
            )
