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


def speaker_model_path() -> Path:
    """Return the path of the bundled speaker model.

    WeSpeaker ResNet34-LM with mean subtraction in the graph; scripts/speaker_model_mean.py
    makes it.
    """
    return _bundled("wespeaker_en_voxceleb_resnet34_LM_mean.onnx")
