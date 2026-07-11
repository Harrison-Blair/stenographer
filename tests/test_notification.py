# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.notification`."""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

from stenographer.notification import DesktopNotification


def _completed(stdout: bytes = b"42\n") -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    return proc


def test_show_startup_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_startup("Ctrl+Alt+D")
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "5000",
        "-p",
        "Stenographer",
        "Ready \u2013 press Ctrl+Alt+D to dictate",
    ]


def test_show_startup_includes_icon_when_available() -> None:
    import pathlib

    notif = DesktopNotification(icon_path=pathlib.Path("/tmp/icon.png"))
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_startup("Ctrl+Alt+D")
        notif.flush()
    called_args = run.call_args[0][0]
    assert "-i" in called_args
    assert "/tmp/icon.png" in called_args


def test_show_startup_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_startup("Ctrl+Alt+D")
        notif.flush()
        run.assert_not_called()


def test_show_startup_marks_unavailable_on_failure() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, [])
        with patch("stenographer.notification.time.monotonic", return_value=123.0):
            notif.show_startup("Ctrl+Alt+D")
            notif.flush()
    assert notif._available is False
    assert notif._last_failure == 123.0


def test_show_startup_marks_unavailable_on_timeout() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired([], 5.0)
        with patch("stenographer.notification.time.monotonic", return_value=456.0):
            notif.show_startup("Ctrl+Alt+D")
            notif.flush()
    assert notif._available is False
    assert notif._last_failure == 456.0


def test_show_startup_marks_unavailable_on_file_not_found() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = FileNotFoundError()
        with patch("stenographer.notification.time.monotonic", return_value=789.0):
            notif.show_startup("Ctrl+Alt+D")
            notif.flush()
    assert notif._available is False
    assert notif._last_failure == 789.0


def test_show_model_loading_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_model_loading()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "0",
        "-p",
        "Stenographer",
        "Loading speech model\u2009\u2014\u2009listening\u2026",
    ]


def test_show_model_loading_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_loading()
        notif.flush()
        run.assert_not_called()


def test_show_model_loading_marks_unavailable_on_failure() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, [])
        with patch("stenographer.notification.time.monotonic", return_value=100.0):
            notif.show_model_loading()
            notif.flush()
    assert notif._available is False
    assert notif._last_failure == 100.0


def test_show_model_unloaded_builds_correct_command() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_model_unloaded()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args == [
        "notify-send",
        "-a",
        "Stenographer",
        "-t",
        "5000",
        "-p",
        "Stenographer",
        "Speech model unloaded (idle)",
    ]


def test_show_model_unloaded_noop_when_unavailable() -> None:
    notif = DesktopNotification()
    notif._available = False
    notif._last_failure = time.monotonic()
    with patch("stenographer.notification.subprocess.run") as run:
        notif.show_model_unloaded()
        notif.flush()
        run.assert_not_called()


def test_second_show_replaces_first_by_id() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed(b"7\n")) as run:
        notif.show_listening()
        notif.show_transcribing()
        notif.flush()
    assert run.call_count == 2
    second = run.call_args_list[1][0][0]
    assert "-r" in second
    assert second[second.index("-r") + 1] == "7"


def test_hide_replaces_own_notification_with_expiring_one() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed(b"9\n")) as run:
        notif.show_listening()
        notif.hide()
        notif.flush()
    assert run.call_count == 2
    hide_cmd = run.call_args_list[1][0][0]
    assert hide_cmd[0] == "notify-send"
    assert hide_cmd[hide_cmd.index("-r") + 1] == "9"
    assert hide_cmd[hide_cmd.index("-t") + 1] == "1"
    assert notif._last_id is None


def test_hide_noop_when_nothing_shown() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run") as run:
        notif.hide()
        notif.flush()
        run.assert_not_called()


def test_show_listening_prompt_enqueues_persistent_notification() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_listening_prompt()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args[-1] == "Listening (prompt)…"
    assert called_args[called_args.index("-t") + 1] == "0"


def test_show_transcribing_prompt_enqueues_persistent_notification() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_transcribing_prompt()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args[-1] == "Transcribing (prompt)…"
    assert called_args[called_args.index("-t") + 1] == "0"


def test_show_rewriting_enqueues_persistent_notification() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_rewriting()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args[-1] == "Rewriting with local LLM…"
    assert called_args[called_args.index("-t") + 1] == "0"


def test_show_prompt_ready_enqueues_transient_notification() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_prompt_ready()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args[-1] == "Prompt ready"
    assert called_args[called_args.index("-t") + 1] == "3000"


def test_show_prompt_failed_enqueues_transient_notification() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_prompt_failed()
        notif.flush()
    called_args = run.call_args[0][0]
    assert called_args[-1] == "Prompt-crafting failed — using raw transcript"
    assert called_args[called_args.index("-t") + 1] == "5000"


def test_prompt_stage_wording_distinct_from_dictate_stage_wording() -> None:
    notif = DesktopNotification()
    notif._available = True
    with patch("stenographer.notification.subprocess.run", return_value=_completed()) as run:
        notif.show_listening()
        notif.show_transcribing()
        notif.show_listening_prompt()
        notif.show_transcribing_prompt()
        notif.show_rewriting()
        notif.show_prompt_ready()
        notif.show_prompt_failed()
        notif.flush()
    bodies = [call[0][0][-1] for call in run.call_args_list]
    dictate_bodies = set(bodies[:2])
    prompt_bodies = bodies[2:]
    assert dictate_bodies.isdisjoint(prompt_bodies)
