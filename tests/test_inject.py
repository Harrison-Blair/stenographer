# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.output.inject`."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from stenographer.output.inject import Injector


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


def test_type_text_unavailable_does_not_call_subprocess(caplog: pytest.LogCaptureFixture) -> None:
    inj = Injector(available=False)
    with (
        caplog.at_level(logging.WARNING),
        patch("stenographer.output.inject.subprocess.run") as run,
    ):
        assert inj.type_text("hello") is False
        run.assert_not_called()
    assert any("wtype not available" in rec.message for rec in caplog.records)


def test_type_text_success_invokes_wtype_with_trailing_space() -> None:
    inj = Injector(available=True)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("hello") is True
        run.assert_called_once()
        call = run.call_args
        assert call.args[0] == ["wtype", "--", "hello "]
        assert call.kwargs["check"] is True
        assert call.kwargs["timeout"] == 5.0
        assert call.kwargs["capture_output"] is True


def test_type_text_without_trailing_space_omits_it() -> None:
    inj = Injector(available=True, append_trailing_space=False)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("hello") is True
        assert run.call_args.args[0] == ["wtype", "--", "hello"]


def test_type_text_empty_returns_true_without_subprocess() -> None:
    inj = Injector(available=True)
    with patch("stenographer.output.inject.subprocess.run") as run:
        assert inj.type_text("") is True
        run.assert_not_called()


def test_type_text_whitespace_only_returns_true_without_subprocess() -> None:
    inj = Injector(available=True)
    with patch("stenographer.output.inject.subprocess.run") as run:
        assert inj.type_text("   ") is True
        run.assert_not_called()


def test_type_text_called_process_error_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    inj = Injector(available=True)
    with (
        caplog.at_level(logging.ERROR),
        patch("stenographer.output.inject.subprocess.run") as run,
    ):
        run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["wtype"], stderr=b"oops")
        assert inj.type_text("hello") is False
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errs, "expected an ERROR log"
    assert "wtype failed" in errs[-1].message
    assert "CalledProcessError" in errs[-1].message


def test_type_text_timeout_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    inj = Injector(available=True)
    with (
        caplog.at_level(logging.ERROR),
        patch("stenographer.output.inject.subprocess.run") as run,
    ):
        run.side_effect = subprocess.TimeoutExpired(cmd=["wtype"], timeout=5.0)
        assert inj.type_text("hello") is False
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errs
    assert "TimeoutExpired" in errs[-1].message


def test_type_text_file_not_found_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    inj = Injector(available=True)
    with (
        caplog.at_level(logging.ERROR),
        patch("stenographer.output.inject.subprocess.run") as run,
    ):
        run.side_effect = FileNotFoundError("wtype not on PATH")
        assert inj.type_text("hello") is False
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errs
    assert "FileNotFoundError" in errs[-1].message


def test_type_text_truncates_long_transcript(caplog: pytest.LogCaptureFixture) -> None:
    inj = Injector(available=True, max_chars=10, append_trailing_space=False)
    payload = "x" * 25
    with (
        caplog.at_level(logging.WARNING),
        patch("stenographer.output.inject.subprocess.run") as run,
    ):
        run.return_value = _completed()
        assert inj.type_text(payload) is True
        assert run.call_args.args[0] == ["wtype", "--", "x" * 10]
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("truncating transcript from 25 to 10 chars" in r.message for r in warns)


def test_type_text_leading_dash_passed_as_positional() -> None:
    inj = Injector(available=True, append_trailing_space=False)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("-rf /") is True
        assert run.call_args.args[0] == ["wtype", "--", "-rf /"]


def test_type_text_unicode_passes_through() -> None:
    inj = Injector(available=True, append_trailing_space=False)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("héllo ☃") is True
        assert run.call_args.args[0] == ["wtype", "--", "héllo ☃"]


def test_type_text_raw_preserves_leading_whitespace_and_skips_trailing_space() -> None:
    inj = Injector(available=True, append_trailing_space=True, max_chars=5)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("  hello world", raw=True) is True
        assert run.call_args.args[0] == ["wtype", "--", "  hello world"]


def test_type_text_raw_bypasses_truncation() -> None:
    inj = Injector(available=True, max_chars=3, append_trailing_space=False)
    with patch("stenographer.output.inject.subprocess.run") as run:
        run.return_value = _completed()
        assert inj.type_text("abcdefg", raw=True) is True
        assert run.call_args.args[0] == ["wtype", "--", "abcdefg"]


def test_type_text_raw_empty_skips_subprocess() -> None:
    inj = Injector(available=True)
    with patch("stenographer.output.inject.subprocess.run") as run:
        assert inj.type_text("", raw=True) is True
        run.assert_not_called()


def test_close_is_noop() -> None:
    inj = Injector(available=True)
    assert inj.close() is None


# --- Integration test (live wtype against a real Wayland session) ---
# OPT-IN ONLY: this test types into whichever window the user currently
# has focused. It MUST be skipped unless the operator has explicitly
# opted in via the STENOGRAPHER_INTEGRATION=1 environment variable and
# a ``wtype`` binary is on PATH. On this machine ``wtype`` is not
# installed, so the test is unconditionally skipped.


@pytest.mark.integration
def test_real_wtype_injects_into_focused_window() -> None:
    if not os.environ.get("STENOGRAPHER_INTEGRATION"):
        pytest.skip("set STENOGRAPHER_INTEGRATION=1 to run integration tests")
    if shutil.which("wtype") is None:
        pytest.skip("wtype not on PATH")
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("WAYLAND_DISPLAY is not set")

    inj = Injector(available=True, append_trailing_space=False)
    assert inj.type_text("") is True
    assert inj.type_text("ok") is True
