# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned files for offline live audio models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LiveModel:
    filename: str
    url: str
    sha256: str


VAD_MODEL = LiveModel(
    "silero_vad.onnx",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
    "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
)
# WeSpeaker ResNet34-LM with mean subtraction in the graph; scripts/speaker_model_mean.py makes it.
SPEAKER_MODEL = LiveModel(
    "wespeaker_en_voxceleb_resnet34_LM_mean.onnx",
    "https://github.com/Harrison-Blair/stenographer/releases/download/speaker-models-1/wespeaker_en_voxceleb_resnet34_LM_mean.onnx",
    "280d78ccc3a8a3ffdf4d9ef867e16faa68d2beb107ad1de7a844285d3522fcd6",
)
LIVE_MODELS = (VAD_MODEL, SPEAKER_MODEL)


def live_model_dir(data_dir: Path) -> Path:
    """Return the directory for the offline live models."""
    return data_dir / "models" / "live"
