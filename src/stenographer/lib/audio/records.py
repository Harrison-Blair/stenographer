# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture measurements and speech-gate verdicts."""

from __future__ import annotations

from dataclasses import dataclass

from stenographer.lib.audio.constants import SAMPLE_RATE


@dataclass(frozen=True)
class GateStats:
    """The energy gate's verdict and the numbers it was reached from."""

    peak_rms: float
    mean_rms: float
    frames_total: int
    frames_above: int
    threshold: float
    passed: bool


@dataclass(frozen=True)
class CaptureStats:
    """What one completed capture cost, for the utterance summary line.

    Negotiated rate, channels and microphone name travel with each capture so
    analytics comparisons survive stream recovery and configuration changes.
    Signal and ADC-clock reductions occur only after callbacks quiesce.
    """

    activate_ms: float
    capture_seconds: float
    input_frames: int
    output_frames: int
    overflow: bool
    capped: bool
    first_callback_at: float | None = None
    activation_to_callback_ms: float | None = None
    max_adc_gap_ms: float | None = None
    adc_discontinuities: int = 0
    device_name: str | None = None
    input_rate: int = SAMPLE_RATE
    channels: int = 1
    finalize_ms: float | None = None
    callback_timing_count: int = 0
    callback_count: int = 0
    callback_metadata_dropped: int = 0
    overflow_count: int = 0
    recovered: bool = False
