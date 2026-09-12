# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable benchmark settings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    id: str
    audio: dict = field(default_factory=dict)
    decode: dict = field(default_factory=dict)
    vad: dict = field(default_factory=dict)
    gate_rms: float | None = None
    post_silence_threshold: float | None = None
