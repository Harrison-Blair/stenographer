# SPDX-License-Identifier: GPL-3.0-or-later
"""notify.py's argv builder, and NotifySendNotifier against a real stub binary.

Nothing here is mocked and no desktop notification is ever fired: the notifier
tests run with PATH pointing at a tmp directory, where ``notify-send`` is
either absent or a shell script this file wrote that records its own argv.
"""

from __future__ import annotations

import logging
import shlex
import time

from stenographer.lib.platform.linux import notify_send_notifier
from stenographer.lib.platform.linux.notify import build_notify_command, bundled_icon_path
from stenographer.lib.platform.linux.notify_send_notifier import NotifySendNotifier

_NOTIFY_LOGGER = "stenographer.lib.platform.linux.notify"


def _stub_notify_send(directory, record):
    """A real ``notify-send`` on PATH that appends its argv to *record*."""
    script = directory / "notify-send"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {shlex.quote(str(record))}\n')
    script.chmod(0o755)
    return script


def _wait_for_argv(record, message, timeout=10.0):
    """The argv the stub recorded once *message* (its last argument) arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if record.exists():
            lines = record.read_text().splitlines()
            if lines and lines[-1] == message:
                return lines
        time.sleep(0.01)
    raise AssertionError(f"notify-send never recorded {message!r}")


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


def test_notifier_stays_a_no_op_when_notify_send_is_absent(tmp_path, monkeypatch):
    """No notify-send on PATH: constructing and firing must degrade silently.

    Availability is decided once, at construction, so a notify-send that turns
    up later is not spawned — the notifier must never re-probe per notification.
    """
    record = tmp_path / "argv"
    monkeypatch.setenv("PATH", str(tmp_path))
    assert NotifySendNotifier.probe() is False

    notifier = NotifySendNotifier()
    _stub_notify_send(tmp_path, record)
    assert NotifySendNotifier.probe() is True
    notifier.error("boom")
    notifier.info("fyi")
    time.sleep(0.2)
    assert not record.exists()


def test_notifier_spawns_notify_send_with_the_urgency_of_each_level(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    _stub_notify_send(tmp_path, record)
    monkeypatch.setenv("PATH", str(tmp_path))

    notifier = NotifySendNotifier()
    notifier.error("copy failed")
    argv = _wait_for_argv(record, "copy failed")
    assert argv[argv.index("-u") + 1] == "critical"
    assert argv[argv.index("-a") + 1] == "Stenographer"
    # The bundled icon is resolved once, at construction, and passed by path.
    assert argv[argv.index("-i") + 1].endswith("stenographer.png")

    record.unlink()
    notifier.info("a newer release is available")
    argv = _wait_for_argv(record, "a newer release is available")
    assert argv[argv.index("-u") + 1] == "normal"


def test_notifier_drops_the_icon_when_the_bundled_asset_cannot_be_read(
    tmp_path, monkeypatch, caplog
):
    """An unreadable icon costs the notification its logo, never its text."""

    def unreadable():
        raise OSError("icon is not readable")

    record = tmp_path / "argv"
    _stub_notify_send(tmp_path, record)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(notify_send_notifier, "bundled_icon_path", unreadable)

    with caplog.at_level(logging.DEBUG, logger=_NOTIFY_LOGGER):
        notifier = NotifySendNotifier()
    assert any("icon_unavailable" in record_.message for record_ in caplog.records)

    notifier.error("copy failed")
    argv = _wait_for_argv(record, "copy failed")
    assert "-i" not in argv


def test_notifier_drops_the_icon_when_the_bundled_asset_is_missing(tmp_path, monkeypatch):
    # A resolvable but absent icon is not an error, just no logo.
    missing = tmp_path / "no-such-icon.png"
    record = tmp_path / "argv"
    _stub_notify_send(tmp_path, record)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(notify_send_notifier, "bundled_icon_path", lambda: missing)

    NotifySendNotifier().error("copy failed")
    assert "-i" not in _wait_for_argv(record, "copy failed")


def test_notifier_survives_a_notify_send_that_cannot_be_executed(tmp_path, monkeypatch, caplog):
    """A broken notifier must never take the daemon down.

    The stub is executable but not a program (no shebang, not a binary), so the
    real spawn raises ``OSError: Exec format error`` — the failure the notifier
    swallows to DEBUG instead of propagating into the delivery path.
    """
    broken = tmp_path / "notify-send"
    broken.write_text("this is not an executable\n")
    broken.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    notifier = NotifySendNotifier()
    with caplog.at_level(logging.DEBUG, logger=_NOTIFY_LOGGER):
        notifier.error("copy failed")
        notifier.info("fyi")
    failures = [r for r in caplog.records if "send_failed" in r.message]
    assert failures
    assert any("OSError" in r.message for r in failures)
