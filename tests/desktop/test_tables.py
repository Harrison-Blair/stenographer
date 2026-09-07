# SPDX-License-Identifier: GPL-3.0-or-later
"""Real offscreen checks for content-proportional desktop tables."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from stenographer_desktop.tables import ContentWidthTable, proportional_widths


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def wait_for(application, predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)
    assert predicate()


def widths(table):
    return [table.columnWidth(column) for column in range(table.columnCount())]


def test_proportional_widths_preserve_overflow_and_assign_every_pixel():
    assert proportional_widths([10, 20, 30], 29) == [10, 20, 30]
    assert proportional_widths([10, 20, 30], 73) == [12, 24, 37]


def test_table_refits_after_content_and_viewport_geometry_changes(application):
    table = ContentWidthTable(["Description", "Count", "Kind"])
    try:
        table.set_rows([("A long value that should receive the most space", "12", "ok")])
        table.resize(820, 130)
        table.show()
        wait_for(application, lambda: sum(widths(table)) == table.viewport().width())
        long_width = widths(table)[0]
        assert long_width > widths(table)[1] > 0

        table.set_rows([("Short", "12", "ok")])
        wait_for(
            application,
            lambda: (
                sum(widths(table)) == table.viewport().width() and widths(table)[0] < long_width
            ),
        )

        natural = [
            max(
                table.horizontalHeader().minimumSectionSize(),
                table.sizeHintForColumn(column),
                table.horizontalHeader().sectionSizeHint(column),
            )
            for column in range(table.columnCount())
        ]
        table.resize(sum(natural) // 2, 130)
        wait_for(application, lambda: widths(table) == natural)
        assert table.horizontalScrollBar().isVisible()

        table.resize(700, 130)
        wait_for(application, lambda: sum(widths(table)) == table.viewport().width())
        table.set_rows([("Short", "12", "ok")] * 30)
        wait_for(
            application,
            lambda: (
                table.verticalScrollBar().isVisible()
                and sum(widths(table)) == table.viewport().width()
            ),
        )
    finally:
        table.close()
        application.processEvents()


def test_hidden_table_refits_when_its_tab_is_revealed(application):
    tabs = QTabWidget()
    table = ContentWidthTable(["Longer heading", "N"])
    tabs.addTab(QWidget(), "Other")
    tabs.addTab(table, "Data")
    try:
        table.set_rows([("longer content", "1")])
        tabs.resize(760, 240)
        tabs.show()
        application.processEvents()
        tabs.resize(540, 240)
        tabs.setCurrentWidget(table)
        wait_for(application, lambda: sum(widths(table)) == table.viewport().width())
        assert widths(table)[0] > widths(table)[1] > 0
    finally:
        tabs.close()
        application.processEvents()
