# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture measurements."""

from __future__ import annotations

from dataclasses import dataclass

from stenographer.lib.audio.constants import SAMPLE_RATE


@dataclass(frozen=True)
class CaptureStats:
    """What one completed capture cost, for the utterance summary line.

    Rate, channels and the microphone source name travel with each capture so
    analytics comparisons survive configuration changes. ``callback_count`` is
    the number of delivered blocks.
    """

    activate_ms: float
    capture_seconds: float
    input_frames: int
    output_frames: int
    capped: bool
    first_callback_at: float | None = None
    activation_to_callback_ms: float | None = None
    device_name: str | None = None
    input_rate: int = SAMPLE_RATE
    channels: int = 1
    finalize_ms: float | None = None
    callback_count: int = 0
