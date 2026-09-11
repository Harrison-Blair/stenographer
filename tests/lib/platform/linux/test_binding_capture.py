# SPDX-License-Identifier: GPL-3.0-or-later
"""Live binding capture: the terminal guard and the device-opening failures.

The terminal half runs against a REAL pty from ``pty.openpty()``, so echo and
canonical mode are really cleared and really restored. The device half only
ever names paths that cannot be opened: reading an actual keyboard belongs to
the opt-in smoke suite, which owns /dev/input.
"""

from __future__ import annotations

import io
import os
import pty
import termios

import pytest

from stenographer.lib.hotkey.errors import BindingCaptureError
from stenographer.lib.platform.linux.binding_capture import (
    _capture_paths,
    _quiet_terminal,
    capture_binding,
)

_MISSING = "/dev/input/stenographer-nonexistent"


def test_quiet_terminal_hides_keystrokes_and_restores_the_terminal_exactly():
    """Echo and line buffering off for the capture window, Ctrl-C untouched.

    ``ISIG`` staying set is the load-bearing part: the prompt tells the user
    they can press Ctrl-C, and clearing it would strand them in the capture.
    """
    master, slave = pty.openpty()
    stdin = os.fdopen(slave, "r")
    try:
        fd = stdin.fileno()
        original = termios.tcgetattr(fd)
        with _quiet_terminal(stdin):
            quiet = termios.tcgetattr(fd)
            assert not quiet[3] & termios.ECHO
            assert not quiet[3] & termios.ICANON
            assert quiet[3] & termios.ISIG
            assert quiet[6][termios.VMIN] == 0
            assert quiet[6][termios.VTIME] == 0
        assert termios.tcgetattr(fd) == original
    finally:
        stdin.close()
        os.close(master)


def test_quiet_terminal_restores_the_terminal_even_when_the_capture_raises():
    master, slave = pty.openpty()
    stdin = os.fdopen(slave, "r")
    try:
        fd = stdin.fileno()
        original = termios.tcgetattr(fd)
        with pytest.raises(KeyboardInterrupt), _quiet_terminal(stdin):
            raise KeyboardInterrupt
        assert termios.tcgetattr(fd) == original
    finally:
        stdin.close()
        os.close(master)


def test_quiet_terminal_refuses_a_stdin_that_is_not_a_terminal(tmp_path):
    # Piped or redirected stdin has no terminal attributes to quiet, and a
    # StringIO has no descriptor at all: both must arrive as the setup flow's
    # own error rather than as io/termios failures.
    with (
        pytest.raises(BindingCaptureError, match="could not prepare the terminal"),
        _quiet_terminal(io.StringIO()),
    ):
        pass

    plain = tmp_path / "stdin.txt"
    plain.write_text("")
    handle = plain.open()
    try:
        with (
            pytest.raises(BindingCaptureError, match="could not prepare the terminal"),
            _quiet_terminal(handle),
        ):
            pass
    finally:
        handle.close()


def test_capture_reports_when_no_keyboard_could_be_detected():
    with pytest.raises(BindingCaptureError, match="no readable main keyboard was detected"):
        _capture_paths(io.StringIO(), [], timeout=0.1)


def test_capture_names_the_device_it_could_not_open():
    """An unopenable device is reported before the terminal is ever touched.

    stdin here is a StringIO, which ``_quiet_terminal`` would reject outright,
    so the message proves the device is opened first — the user is told which
    path failed instead of being told their terminal is wrong.
    """
    with pytest.raises(BindingCaptureError) as raised:
        _capture_paths(io.StringIO(), [_MISSING], timeout=0.1)
    assert f"could not open hotkey device {_MISSING}" in str(raised.value)


def test_capture_binding_uses_an_explicit_device_instead_of_auto_detecting():
    # An explicit hotkey.device is honoured verbatim: a stale path fails on
    # that path rather than silently capturing from some other keyboard.
    with pytest.raises(BindingCaptureError) as raised:
        capture_binding(io.StringIO(), _MISSING, timeout=0.1)
    assert _MISSING in str(raised.value)
