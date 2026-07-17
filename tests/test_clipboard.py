# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.output.clipboard`."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
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
        # The primary-selection call is asserted by
        # test_copy_populates_primary_selection; this test pins the regular
        # clipboard invocation's arguments.
        call = run.call_args_list[0]
        assert call.args[0] == ["wl-copy"]
        assert call.kwargs["input"] == b"hello"
        assert call.kwargs["check"] is True
        assert call.kwargs["timeout"] == 10.0
        # Not capture_output: wl-copy's forked daemon inherits captured pipes
        # and holds them open, hanging the call until its timeout. See
        # test_copy_does_not_capture_subprocess_pipes.
        assert call.kwargs["stdout"] is subprocess.DEVNULL
        assert call.kwargs["stderr"] is subprocess.DEVNULL


def test_copy_populates_primary_selection() -> None:
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.return_value = _completed()
        assert mgr.copy("hello") is True
        assert run.call_count == 2
        regular, primary = run.call_args_list
        assert regular.args[0] == ["wl-copy"]
        assert primary.args[0] == ["wl-copy", "--primary"]
        # Both selections must carry the same text.
        assert regular.kwargs["input"] == b"hello"
        assert primary.kwargs["input"] == b"hello"


def test_copy_does_not_capture_subprocess_pipes() -> None:
    """Pin the *call shape*: ``copy()`` must not capture wl-copy's pipes.

    ``wl-copy`` forks and serves the selection in the background, and the
    forked child inherits any stdout/stderr pipes ``capture_output=True``
    creates. ``subprocess.run`` then waits for EOF on pipes the daemon holds
    open indefinitely, so the call blocks until its timeout fires. This test
    pins the call shape only -- it cannot prove the behaviour, because it
    mocks the very subprocess whose real fork is the defect. Its job is to
    stop a future refactor from "tidying" the call back to captured pipes
    without noticing. ``test_clipboard_copy_real_wl_copy_round_trip`` is the
    test that proves the behaviour.
    """
    mgr = ClipboardManager(available=True)
    with patch("stenographer.output.clipboard.subprocess.run") as run:
        run.return_value = _completed()
        assert mgr.copy("hello") is True
        assert run.call_count == 2
        for call in run.call_args_list:
            assert call.kwargs.get("capture_output") is not True, (
                f"{call.args[0]} must not capture wl-copy's pipes: the forked "
                "clipboard daemon inherits them and holds them open"
            )
            assert call.kwargs["stdout"] is subprocess.DEVNULL
            assert call.kwargs["stderr"] is subprocess.DEVNULL


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


def _save_selection(*, primary: bool) -> bytes | None:
    argv = ["wl-paste", "--no-newline"] + (["--primary"] if primary else [])
    try:
        result = subprocess.run(argv, check=True, capture_output=True, timeout=10.0)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None
    return result.stdout


def _restore_selection(value: bytes | None, *, primary: bool) -> None:
    argv = ["wl-copy"] + (["--primary"] if primary else [])
    with contextlib.suppress(
        subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError
    ):
        # stdout/stderr are DEVNULL, not captured: wl-copy forks a daemon that
        # inherits captured pipes and holds them open, which would make this
        # restore block for its full timeout on the way out of every test.
        subprocess.run(
            argv,
            input=value if value is not None else b"",
            check=True,
            timeout=10.0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _read_selection(*, primary: bool) -> str | None:
    value = _save_selection(primary=primary)
    return None if value is None else value.decode("utf-8")


def _require_live_clipboard() -> None:
    if not os.environ.get("STENOGRAPHER_INTEGRATION"):
        pytest.skip("set STENOGRAPHER_INTEGRATION=1 to run integration tests")
    for tool in ("wl-copy", "wl-paste"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH")
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("WAYLAND_DISPLAY is not set")


@pytest.mark.integration
def test_clipboard_copy_real_wl_copy_round_trip() -> None:
    """``copy()`` against a real ``wl-copy``: returns True, does not hang,
    and populates *both* selections.

    This is the test the mocked unit suite structurally cannot be: the defect
    lives in the real ``wl-copy``'s fork, which every mock replaces. Against
    unchanged code this fails on the real 10s timeout with ``copy()``
    returning False.

    The duration bound is the behaviour under test -- "does not hang" -- not a
    latency budget, so the bound is deliberately generous. The ``--primary``
    readback pins that the loop reaches its second call at all: pre-fix,
    ``copy()`` returned False on the first wl-copy's timeout and the primary
    selection was never written.
    """
    _require_live_clipboard()

    saved_regular = _save_selection(primary=False)
    saved_primary = _save_selection(primary=True)
    try:
        mgr = ClipboardManager(available=True)
        token = f"stenographer-fthr021-{uuid.uuid4()}"

        start = time.monotonic()
        result = mgr.copy(token)
        elapsed = time.monotonic() - start

        assert result is True, (
            f"copy() returned False after {elapsed:.2f}s -- if elapsed is near "
            "the 10.0s timeout, wl-copy's forked daemon is holding captured pipes"
        )
        assert elapsed < 5.0, (
            f"copy() took {elapsed:.2f}s; it must not block on wl-copy's "
            "forked daemon holding inherited pipes"
        )
        assert _read_selection(primary=False) == token, "regular clipboard not populated"
        assert _read_selection(primary=True) == token, (
            "primary selection not populated -- copy() never reached ['wl-copy', '--primary']"
        )
        # Also exercise ClipboardManager.read() against the real wl-paste,
        # preserving the coverage of the superseded test_real_wl_copy_round_trip.
        assert mgr.read() == token
    finally:
        _restore_selection(saved_regular, primary=False)
        _restore_selection(saved_primary, primary=True)
