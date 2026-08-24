# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for notify.py: build_notify_command argv only.

The Popen send in NotifySendNotifier.error/info is never mock-tested; a broken
notifier degrades to a no-op and is validated by real use, not by asserting a
mocked call.
"""

from __future__ import annotations

from stenographer.platform.linux.notify import build_notify_command, bundled_icon_path


def test_build_notify_command_exact_argv():
    assert build_notify_command("copy failed") == [
        "notify-send",
        "-a",
        "Stenographer",
        "-u",
        "critical",
        "Stenographer",
        "copy failed",
    ]


def test_build_notify_command_exact_argv_at_normal_urgency():
    # The update notice is advisory, so it must not borrow the error urgency.
    assert build_notify_command("a newer release is available", "normal") == [
        "notify-send",
        "-a",
        "Stenographer",
        "-u",
        "normal",
        "Stenographer",
        "a newer release is available",
    ]


def test_build_notify_command_preserves_message_verbatim():
    message = "unusual: spaces, punctuation! and 'quotes'"
    argv = build_notify_command(message)
    # The message is the last argument, passed through unchanged (never shell-joined).
    assert argv[-1] == message
    # It is a critical, app-named notification.
    assert argv[:2] == ["notify-send", "-a"]
    assert "critical" in argv


def test_build_notify_command_places_the_icon_before_the_summary():
    # Options precede the positional pair, per notify-send's documented usage:
    # "notify-send [OPTION...] <SUMMARY> [BODY]".
    assert build_notify_command("update available", "normal", "/opt/steno/icon.png") == [
        "notify-send",
        "-a",
        "Stenographer",
        "-u",
        "normal",
        "-i",
        "/opt/steno/icon.png",
        "Stenographer",
        "update available",
    ]


def test_build_notify_command_omits_the_icon_flag_when_there_is_no_icon():
    assert "-i" not in build_notify_command("copy failed", "critical", None)


def test_bundled_icon_is_actually_present_in_the_package():
    # The path is package-anchored so the frozen bundle resolves it too; here
    # it only has to name a real file in the source tree.
    icon = bundled_icon_path()
    assert icon.is_file()
    assert icon.name == "stenographer.png"
