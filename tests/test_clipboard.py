# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.output.clipboard`."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import uuid
from unittest.mock import patch

import pytest

from stenographer.output.clipboard import ClipboardManager


def _completed(
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# --- Unit tests (mocked subprocess) ---


def test_copy_unavailable_does_not_call_subprocess() -> None:
    mgr = ClipboardManager(available=False)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        assert mgr.copy("hello") is False
        run.assert_not_called()


def test_copy_success_returns_true_and_pipes_input() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.return_value = _completed()
        assert mgr.copy("hello") is True
        run.assert_called_once()
        call = run.call_args
        assert call.args[0] == ["wl-copy"]
        assert call.kwargs["input"] == b"hello"
        assert call.kwargs["check"] is True
        assert call.kwargs["timeout"] == 10.0
        assert call.kwargs["capture_output"] is True


def test_copy_called_process_error_returns_false() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["wl-copy"],
            stderr=b"failed",
        )
        assert mgr.copy("hello") is False


def test_copy_timeout_returns_false() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=["wl-copy"], timeout=10.0)
        assert mgr.copy("hello") is False


def test_copy_file_not_found_returns_false() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.side_effect = FileNotFoundError("wl-copy not on PATH")
        assert mgr.copy("hello") is False


def test_read_success_strips_trailing_newline() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.return_value = _completed(stdout=b"clipboard contents\n")
        assert mgr.read() == "clipboard contents"
        run.assert_called_once()
        call = run.call_args
        assert call.args[0] == ["wl-paste", "--no-newline"]
        assert call.kwargs["check"] is True
        assert call.kwargs["capture_output"] is True
        assert call.kwargs["timeout"] == 10.0


def test_read_success_without_trailing_newline() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.return_value = _completed(stdout=b"clipboard contents")
        assert mgr.read() == "clipboard contents"


def test_read_unavailable_returns_none() -> None:
    mgr = ClipboardManager(available=False)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        assert mgr.read() is None
        run.assert_not_called()


def test_read_called_process_error_returns_none() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["wl-paste"],
            stderr=b"oops",
        )
        assert mgr.read() is None


def test_close_is_noop() -> None:
    mgr = ClipboardManager(available=True)
    assert mgr.close() is None


# --- Integration tests (live wl-copy / wl-paste) ---
# Gated by the STENOGRAPHER_INTEGRATION env var so that running the
# regular test suite does not mutate the user's actual Wayland clipboard.


def _save_clipboard() -> bytes | None:
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            check=True,
            capture_output=True,
            timeout=10.0,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None
    return result.stdout


def _restore_clipboard(value: bytes | None) -> None:
    with contextlib.suppress(
        subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError
    ):
        subprocess.run(
            ["wl-copy"],
            input=value if value is not None else b"",
            check=True,
            timeout=10.0,
            capture_output=True,
        )


@pytest.mark.integration
def test_real_wl_copy_round_trip() -> None:
    if not os.environ.get("STENOGRAPHER_INTEGRATION"):
        pytest.skip("set STENOGRAPHER_INTEGRATION=1 to run integration tests")
    if shutil.which("wl-copy") is None:
        pytest.skip("wl-copy not on PATH")
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("WAYLAND_DISPLAY is not set")

    saved = _save_clipboard()
    try:
        mgr = ClipboardManager(available=True)
        sentinel = f"stenographer-test-{uuid.uuid4()}"
        assert mgr.copy(sentinel) is True
        result = mgr.read()
        assert result is not None
        assert sentinel in result, f"expected {sentinel!r} in clipboard, got {result!r}"
    finally:
        _restore_clipboard(saved)
