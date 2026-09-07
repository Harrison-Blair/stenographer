# SPDX-License-Identifier: GPL-3.0-or-later
"""Real offscreen widgets and temporary-database/settings workflows; no microphone."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from stenographer.analytics import AnalyticsSession
from stenographer.config import Config
from stenographer.transcribe.pipeline import UtteranceRecord, analytics_metrics
from stenographer_desktop.app import Window
from stenographer_desktop.services import DesktopServices


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def wait_for(application, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    assert predicate()


def test_theme_overrides_widget_fonts_and_preserves_text_roles():
    script = """
from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLineEdit, QListWidget, QPushButton,
    QStatusBar, QTableWidget, QVBoxLayout, QWidget,
)
from stenographer_desktop.charts import WordTrend
from stenographer_desktop.theme import TOKENS, apply_theme

app = QApplication([])
root = QWidget()
layout = QVBoxLayout(root)
labels = {}
for role in ("brand", "title", "caption", "section", "headline", "muted"):
    labels[role] = QLabel(role)
    labels[role].setProperty("role", role)
    layout.addWidget(labels[role])
table = QTableWidget(1, 1)
combo = QComboBox()
combo.addItem("Choice")
rail = QListWidget()
rail.setObjectName("rail")
controls = (
    QPushButton("Button"), QLineEdit("Line edit"), table, table.horizontalHeader(), rail,
    combo, combo.view(), QStatusBar(), WordTrend(),
)
system_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
assert QFontInfo(system_font).family() != "Caveat"
for widget in (*labels.values(), *controls):
    widget.setFont(system_font)
for widget in (controls[0], controls[1], table, rail, combo, controls[-2], controls[-1]):
    layout.addWidget(widget)
apply_theme(app)
root.show()
app.processEvents()
assert all(
    QFontInfo(widget.font()).family() == "Caveat"
    for widget in (*labels.values(), *controls)
)
assert {role: label.font().pointSize() for role, label in labels.items()} == {
    "brand": TOKENS.brand_pt, "title": TOKENS.title_pt, "caption": TOKENS.caption_pt,
    "section": TOKENS.section_pt, "headline": TOKENS.headline_pt, "muted": TOKENS.body_pt,
}
assert labels["brand"].font().weight() == 600
assert labels["headline"].font().weight() == 700
assert controls[0].font().pointSize() == TOKENS.body_pt
assert rail.font().pixelSize() == TOKENS.rail_label_px
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr


def test_actual_window_settings_and_analytics_without_daemon(application, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config_path = tmp_path / "config.toml"
    config_path.write_text("# preserved\n[stenographer.feedback]\nmute = false # retained\n")
    window = Window(DesktopServices(config_path, tmp_path / "analytics.sqlite3"))
    try:
        window.show()
        wait_for(application, lambda: window.document is not None and window.analytics_loaded)
        assert window.navigation.count() == 5
        rail = window.findChild(QWidget, "railFrame")
        quill = window.findChild(QLabel, "quill")
        assert rail.width() == 96
        assert window.navigation.width() == 96
        assert window.navigation.gridSize().width() == 96
        assert window.navigation.gridSize().height() == 56
        assert window.navigation.iconSize().width() == 20
        assert quill.pixmap().deviceIndependentSize().width() == 60
        assert quill.pixmap().deviceIndependentSize().height() == 60
        assert quill.alignment() == Qt.AlignmentFlag.AlignCenter
        assert "analytics.enabled" in window.editors
        assert "analytics.resource_profiling" in window.editors
        window.navigation.setCurrentRow(2)
        window.editors["feedback.mute"].setChecked(True)
        window.save_settings()
        wait_for(application, lambda: window.save_button.isEnabled())
        assert Config.load(config_path).feedback.mute
        assert "# preserved" in config_path.read_text()
        assert "mute = true # retained" in config_path.read_text()
        assert not window.grab().isNull()
        assert "Apply while idle" in window.saved_state.text()
        window.editors["audio.max_recording_seconds"].setText("-1")
        window.save_settings()
        assert "audio.max_recording_seconds" in window.saved_state.text()
        assert Config.load(config_path).audio.max_recording_seconds != -1
    finally:
        window.close()
        application.processEvents()


def test_malformed_settings_do_not_prevent_historical_analytics(application, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not valid TOML")
    window = Window(DesktopServices(config_path, tmp_path / "analytics.sqlite3"))
    try:
        wait_for(
            application,
            lambda: window.analytics_loaded and "Cannot load" in window.saved_state.text(),
        )
        assert not window.save_button.isEnabled()
        assert window.document is None
        assert config_path.read_text() == "this is not valid TOML"
    finally:
        window.close()
        application.processEvents()


def test_decode_comparisons_use_persisted_utterance_measurements(
    application, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "analytics.sqlite3"
    session = AnalyticsSession(path)
    try:
        for index, (model, duration) in enumerate(
            [("one", 10.0), ("one", 30.0), ("one", None), ("two", None)]
        ):
            record = UtteranceRecord(utt=index, decode_ms=duration)
            identity = session.start(record.utt, context={"model": model})
            session.finish(identity, "success", analytics_metrics(record))
    finally:
        assert session.close()

    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    window = Window(DesktopServices(config_path, path))
    try:
        wait_for(application, lambda: window.analytics_loaded)
        window.compare_metric.setCurrentText("decode_ms")
        assert window.compare_metric.currentText() == "decode_ms"
        assert window.compare_metric.findText("inference_ms") == -1
        assert len(window.rows) == 4

        def cells(table):
            return [
                [table.item(row, column).text() for column in range(table.columnCount())]
                for row in range(table.rowCount())
            ]

        assert cells(window.comparisons) == [
            ["one", "2", "1", "20.0", "30.0", "30.0"],
            ["two", "0", "1", "Unavailable", "Unavailable", "Unavailable"],
        ]
        assert sum(int(row[1]) for row in cells(window.histogram)) == 2
        window.rows = [row for row in window.rows if "decode_ms" not in row["metrics"]]
        window.refresh_comparison()
        assert window.histogram.rowCount() == 0
        assert all(row[1:3] == ["0", "1"] for row in cells(window.comparisons))
    finally:
        window.close()
        application.processEvents()


def test_desktop_imports_with_cli_handlers_blocked():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['stenographer.cli'] = None; "
            "import stenographer_desktop.app; import stenographer_desktop.services; "
            "from stenographer.settings import ConfigDocument; "
            "from stenographer.calibration import estimate_spectrum_profile",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_headless_daemon_imports_without_desktop_or_qt():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['stenographer_desktop'] = None; "
            "sys.modules['PySide6'] = None; import stenographer.daemon; "
            "import stenographer.cli; import stenographer.settings; import stenographer.analytics",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_focused_shortcut_captures_tab_and_waits_for_modifier_release(application):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QWidget

    from stenographer.platform import current_platform
    from stenographer_desktop.app import BindingDialog

    parent = QWidget()
    dialog = BindingDialog(current_platform(), parent)
    try:
        dialog.show()
        QTest.keyPress(dialog, Qt.Key.Key_Control)
        QTest.keyPress(dialog, Qt.Key.Key_Tab)
        QTest.keyRelease(dialog, Qt.Key.Key_Tab)
        assert dialog.isVisible()
        QTest.keyRelease(dialog, Qt.Key.Key_Control)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.binding == "KEY_LEFTCTRL+KEY_TAB"
    finally:
        dialog.reject()
        parent.close()


def test_shortcut_dialog_rejects_lost_lease_without_a_successful_status_callback(application):
    import threading

    from PySide6.QtWidgets import QDialog, QWidget

    from stenographer.platform import current_platform
    from stenographer_desktop.app import BindingDialog

    cancellation = threading.Event()
    parent = QWidget()
    dialog = BindingDialog(current_platform(), parent, cancellation)
    try:
        dialog.show()
        assert dialog.isVisible()
        cancellation.set()
        wait_for(application, lambda: not dialog.isVisible(), timeout=0.5)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.binding == ""
    finally:
        dialog.reject()
        parent.close()
