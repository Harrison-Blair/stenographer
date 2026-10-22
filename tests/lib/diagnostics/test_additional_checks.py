# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import pathlib

from stenographer.lib.diagnostics import additional_checks
from stenographer.lib.live.models import LIVE_MODELS


def _executable(directory: pathlib.Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def test_system_capture_check_requires_tools_and_a_default_sink(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir, "pw-record", "exit 0")
    _executable(bin_dir, "pw-link", "exit 0")
    _executable(bin_dir, "pactl", 'printf "alsa_output.test\\n"')
    monkeypatch.setenv("PATH", str(bin_dir))

    check = additional_checks.system_capture_check()

    assert check.status == "ok"
    assert "alsa_output.test" in check.detail

    (bin_dir / "pw-link").unlink()
    missing_tool = additional_checks.system_capture_check()
    assert missing_tool.status == "warn"
    assert "pw-link" in missing_tool.detail

    _executable(bin_dir, "pw-link", "exit 0")
    _executable(bin_dir, "pactl", "exit 0")
    missing_sink = additional_checks.system_capture_check()
    assert missing_sink.status == "warn"
    assert "default sink" in missing_sink.detail.casefold()


def test_live_models_check_uses_the_pinned_model_files(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    for model in LIVE_MODELS:
        (model_dir / model.filename).write_bytes(b"model")

    assert additional_checks.live_models_check(model_dir).status == "ok"

    (model_dir / LIVE_MODELS[0].filename).unlink()
    missing = additional_checks.live_models_check(model_dir)
    assert missing.status == "warn"
    assert LIVE_MODELS[0].filename in missing.detail


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


def test_system_capture_check_reports_a_failed_default_sink_probe(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir, "pw-record", "exit 0")
    _executable(bin_dir, "pw-link", "exit 0")
    _executable(bin_dir, "pactl", "exit 1")
    monkeypatch.setenv("PATH", os.fspath(bin_dir))

    check = additional_checks.system_capture_check()

    assert check.status == "warn"
    assert "default sink" in check.detail.casefold()
    assert check.fix


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
