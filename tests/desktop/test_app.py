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

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stenographer.config import Config
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
