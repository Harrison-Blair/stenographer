# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pathlib

import pytest

from stenographer.lib.diagnostics import additional_checks
from stenographer.lib.platform.errors import SpeakerDiarizerError


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


def test_python_venv_check_is_collected_for_doctor(monkeypatch):
    monkeypatch.setattr(additional_checks, "speaker_reason", lambda: None)
    ids = [check.check_id for check in additional_checks.collect_additional_checks()]

    assert "python_venv" in ids


def test_speaker_check_reports_why_speaker_labels_cannot_run():
    reason = "speaker separation needs an AVX2 CPU"

    assert additional_checks.speaker_check(None) == additional_checks.DiagnosticCheck(
        "speakers", "ok", "available", ""
    )
    check = additional_checks.speaker_check(reason)
    assert (check.check_id, check.status, check.detail) == ("speakers", "warn", reason)


class _Diarizer:
    def __init__(self, reason=None, error=None):
        self.reason = reason
        self.error = error
        self.files = []
        self.closed = False

    def unavailable_reason(self):
        return self.reason

    def diarize_file(self, source, **_options):
        self.files.append(len(source))
        if self.error is not None:
            raise self.error
        return ()

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("diarizer", "status", "detail"),
    [
        (_Diarizer(), "ok", "available"),
        (_Diarizer(reason="speaker separation needs an AVX2 CPU"), "warn", "AVX2"),
        (
            _Diarizer(error=SpeakerDiarizerError("speaker model could not load")),
            "warn",
            "could not load",
        ),
    ],
    ids=["available", "host", "helper-failed"],
)
def test_the_speaker_check_starts_the_helper_and_shows_its_failure(
    monkeypatch, diarizer, status, detail
):
    platform = type("Platform", (), {"speaker_diarizer": lambda _self: diarizer})()
    monkeypatch.setattr(additional_checks, "current_platform", lambda: platform)

    checks = {check.check_id: check for check in additional_checks.collect_additional_checks()}

    assert (checks["speakers"].status, detail in checks["speakers"].detail) == (status, True)
    # Only a host that can run it starts the helper, on one second of silence.
    assert diarizer.files == ([] if diarizer.reason else [16000])
    assert diarizer.closed


def test_the_speaker_check_shows_why_the_helper_process_cannot_start(monkeypatch):
    from tests.lib.platform.linux.failing_start import unstartable_diarizer

    diarizer, _context = unstartable_diarizer(monkeypatch)
    platform = type("Platform", (), {"speaker_diarizer": lambda _self: diarizer})()
    monkeypatch.setattr(additional_checks, "current_platform", lambda: platform)

    check = {c.check_id: c for c in additional_checks.collect_additional_checks()}["speakers"]

    assert check.status == "warn"
    assert "could not start" in check.detail
