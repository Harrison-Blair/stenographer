# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pathlib

import pytest

from stenographer.lib.diagnostics import additional_checks


def _executable(directory: pathlib.Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("tools", "pactl_body", "status", "detail_fragment"),
    [
        (("pw-record", "pw-link"), 'printf "alsa_output.test\\n"', "ok", "alsa_output.test"),
        (("pw-record",), 'printf "alsa_output.test\\n"', "warn", "pw-link"),
        (("pw-record", "pw-link"), "exit 0", "warn", "no default sink"),
        (("pw-record", "pw-link"), "exit 1", "warn", "could not find the default sink"),
    ],
    ids=["ok", "missing-pw-link", "empty-sink-output", "pactl-exit-1"],
)
def test_system_capture_check_requires_tools_and_a_default_sink(
    monkeypatch, tmp_path, tools, pactl_body, status, detail_fragment
):
    for tool in tools:
        _executable(tmp_path, tool, "exit 0")
    _executable(tmp_path, "pactl", pactl_body)
    monkeypatch.setenv("PATH", str(tmp_path))

    check = additional_checks.system_capture_check()

    assert check.status == status
    assert detail_fragment in check.detail
    assert bool(check.fix) == (status == "warn")


def test_ffmpeg_check_uses_the_executable_path(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))

    missing = additional_checks.ffmpeg_check()
    assert missing.status == "warn"
    assert "ffmpeg" in missing.detail.casefold()

    _executable(bin_dir, "ffmpeg", "exit 0")
    available = additional_checks.ffmpeg_check()
    assert available.status == "ok"
    assert "ffmpeg" in available.detail


def test_python_venv_check_passes_for_a_python_that_can_make_a_venv():
    import sys

    check = additional_checks.python_venv_check(sys.executable)

    assert check.check_id == "python_venv"
    assert check.status == "ok"


def test_python_venv_check_warns_with_the_apt_fix_when_venv_would_fail(tmp_path):
    # A python3 whose stdlib lacks ensurepip, as on Ubuntu without python3-venv.
    _executable(tmp_path, "python3", "exit 1")

    check = additional_checks.python_venv_check(str(tmp_path / "python3"))

    assert check.status == "warn"
    assert "model download --asr" in check.detail
    assert check.fix == "Run `sudo apt install python3-venv`."


def test_python_venv_check_is_collected_for_doctor():
    ids = [check.check_id for check in additional_checks.collect_additional_checks()]

    assert "python_venv" in ids
