# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned files for offline live audio models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveModel:
    filename: str
    url: str
    sha256: str


LIVE_MODELS = (
    LiveModel(
        "silero_vad.onnx",
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
    ),
    LiveModel(
        "nemo_en_titanet_small.onnx",
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx",
        "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e",
    ),
)
