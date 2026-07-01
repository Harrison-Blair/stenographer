# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.notification`."""

from __future__ import annotations

import subprocess
import time
from unittest.mock import patch

from stenographer.notification import DesktopNotification


def test_show_startup_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_startup("Ctrl+Alt+D")
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "5000",
        "Stenographer",
        "Ready \u2013 press Ctrl+Alt+D to dictate",
    ]


def test_show_startup_includes_icon_when_available() -> None:
    import pathlib

    notif = DesktopNotification(icon_path=pathlib.Path("/tmp/icon.png"))
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_startup("Ctrl+Alt+D")
    called_args = run.call_args[0][0]
    assert "-i" in called_args
    assert "/tmp/icon.png" in called_args


def test_show_startup_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_startup("Ctrl+Alt+D")
        run.assert_not_called()


def test_show_startup_marks_unavailable_on_failure() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, [])
        with patch("stenographer.notification.time.monotonic", return_value=123.0):
            notif.show_startup("Ctrl+Alt+D")
    assert notif._available is False
    assert notif._last_failure == 123.0


def test_show_startup_marks_unavailable_on_timeout() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired([], 5.0)
        with patch("stenographer.notification.time.monotonic", return_value=456.0):
            notif.show_startup("Ctrl+Alt+D")
    assert notif._available is False
    assert notif._last_failure == 456.0


def test_show_startup_marks_unavailable_on_file_not_found() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = FileNotFoundError()
        with patch("stenographer.notification.time.monotonic", return_value=789.0):
            notif.show_startup("Ctrl+Alt+D")
    assert notif._available is False
    assert notif._last_failure == 789.0


def test_show_model_loading_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_loading()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "0",
        "Stenographer",
        "Loading speech model\u2009\u2014\u2009listening\u2026",
    ]


def test_show_model_loading_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_loading()
        run.assert_not_called()


def test_show_model_loading_marks_unavailable_on_failure() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, [])
        with patch("stenographer.notification.time.monotonic", return_value=100.0):
            notif.show_model_loading()
    assert notif._available is False
    assert notif._last_failure == 100.0


def test_show_model_ready_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_ready()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "5000",
        "Stenographer",
        "Model ready",
    ]


def test_show_model_ready_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_ready()
        run.assert_not_called()


def test_show_model_unloaded_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_unloaded()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "5000",
        "Stenographer",
        "Speech model unloaded (idle)",
    ]


def test_show_model_unloaded_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_unloaded()
        run.assert_not_called()
