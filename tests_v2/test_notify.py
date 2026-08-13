# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for notify.py: build_notify_command argv only.

The Popen send in Notifier.error is never mock-tested (§6.2); a broken notifier
degrades to a no-op and is validated by real use, not by asserting a mocked call.
"""

from __future__ import annotations

from stenographer_v2.notify import build_notify_command


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


def test_build_notify_command_preserves_message_verbatim():
    message = "unusual: spaces, punctuation! and 'quotes'"
    argv = build_notify_command(message)
    # The message is the last argument, passed through unchanged (never shell-joined).
    assert argv[-1] == message
    # It is a critical, app-named notification.
    assert argv[:2] == ["notify-send", "-a"]
    assert "critical" in argv
