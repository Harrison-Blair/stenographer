# SPDX-License-Identifier: GPL-3.0-or-later
"""Paths of the voice models that ship with the app."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def _bundled(filename: str) -> Path:
    return Path(str(files("stenographer"))) / "assets" / "models" / filename


def vad_model_path() -> Path:
    """Return the path of the bundled Silero VAD model."""
    return _bundled("silero_vad.onnx")
