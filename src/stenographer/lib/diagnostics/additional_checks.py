# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional host checks for hub and doctor reports."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

from stenographer.lib.live.models import LIVE_MODELS


@dataclass(frozen=True)
class DiagnosticCheck:
    """One passing or warned optional capability."""

    check_id: str
    status: str
    detail: str
    fix: str


def system_capture_check() -> DiagnosticCheck:
    """Check the PipeWire tools and the configured default sink without capture."""
    for executable in ("pw-record", "pw-link"):
        if shutil.which(executable) is None:
            return DiagnosticCheck(
                "system_capture",
                "warn",
                f"{executable} is not installed",
                "Install PipeWire and its command-line tools.",
            )
    pactl = shutil.which("pactl")
    if pactl is None:
        return DiagnosticCheck(
            "system_capture",
            "warn",
            "pactl is not installed; the default sink cannot be checked",
            "Install pipewire-pulse and check the default output device.",
        )
    try:
        result = subprocess.run(
            [pactl, "get-default-sink"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return DiagnosticCheck(
            "system_capture",
            "warn",
            "pactl could not find the default sink",
            "Select an active PipeWire output device.",
        )
    sink = result.stdout.strip()
    if not sink:
        return DiagnosticCheck(
            "system_capture",
            "warn",
            "pactl returned no default sink",
            "Select an active PipeWire output device.",
        )
    return DiagnosticCheck(
        "system_capture",
        "ok",
        f"default sink: {sink}",
        "",
    )


def live_models_check(model_dir: pathlib.Path | None = None) -> DiagnosticCheck:
    """Check that both pinned live models are present in the local cache."""
    if model_dir is None:
        from stenographer.lib.platform import current_platform

        model_dir = current_platform().data_dir(os.environ, pathlib.Path.home()) / "models" / "live"
    missing = [
        model.filename for model in LIVE_MODELS if not (model_dir / model.filename).is_file()
    ]
    if missing:
        return DiagnosticCheck(
            "live_models_cached",
            "warn",
            f"missing: {', '.join(missing)}",
            "Run `stenographer model download --live`.",
        )
    return DiagnosticCheck(
        "live_models_cached",
        "ok",
        "VAD and speaker models are cached",
        "",
    )


def ffmpeg_check() -> DiagnosticCheck:
    """Check for the system FFmpeg executable used to read M4A and AAC files."""
    if shutil.which("ffmpeg") is None:
        return DiagnosticCheck(
            "ffmpeg",
            "warn",
            "ffmpeg is not installed",
            "Install ffmpeg with the system package manager.",
        )
    return DiagnosticCheck("ffmpeg", "ok", "ffmpeg is installed", "")


def python_venv_check(python: str | None = None) -> DiagnosticCheck:
    """Check that the system Python 3 can make the temporary venv of the ASR model build."""
    from stenographer.lib.transcribe import bark_download

    python = bark_download.SYSTEM_PYTHON if python is None else python
    if not bark_download.venv_available(python):
        return DiagnosticCheck(
            "python_venv",
            "warn",
            f"`{python} -m venv` would fail; `stenographer model download --asr` needs it",
            "Run `sudo apt install python3-venv`.",
        )
    return DiagnosticCheck("python_venv", "ok", f"`{python} -m venv` works", "")


def collect_additional_checks(
    *, live_model_dir: pathlib.Path | None = None
) -> tuple[DiagnosticCheck, ...]:
    """Collect optional checks that never change the required capability gate."""
    return (
        system_capture_check(),
        live_models_check(live_model_dir),
        ffmpeg_check(),
        python_venv_check(),
    )
