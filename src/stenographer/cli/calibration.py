# SPDX-License-Identifier: GPL-3.0-or-later
"""One-shot calibration for the display-only microphone spectrum floor.

Calibration is deliberately separate from capture gating and transcription. It
records one fixed sample, analyzes it only after PortAudio has stopped, and
returns a value for the existing ``feedback.spectrum_floor_dbfs`` setting.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import numpy as np

from stenographer.audio import Recorder
from stenographer.overlay.spectrum import (
    MAX_SPECTRUM_FLOOR_DBFS,
    MIN_SPECTRUM_FLOOR_DBFS,
    WINDOW_SECONDS,
    _band_dbfs,
)

COUNTDOWN_SECONDS = 3
CAPTURE_SECONDS = 5
DISCARD_SECONDS = 0.5
# PortAudio callbacks and scheduler wakeups do not land exactly on five seconds.
MIN_CAPTURE_SECONDS = 4.5
CALIBRATION_HEADROOM_DB = 3.0
NONSTATIONARY_SPREAD_DB = 12.0


class CalibrationError(ValueError):
    """The recorded room-noise sample cannot produce a safe display floor."""


def _validate_sample_rate(sample_rate: int) -> None:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("calibration sample rate must be a positive integer")


def estimate_spectrum_floor(samples: object, sample_rate: int) -> float:
    """Estimate a fixed display floor from a nominal five-second quiet capture.

    The first half-second is discarded. Remaining complete, non-overlapping
    32 ms windows use the same 18-band measurement as the live overlay. The
    loudest band's 95th percentile receives 3 dB of headroom and is rounded
    upward to a whole dB.
    """
    _validate_sample_rate(sample_rate)
    try:
        audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("calibration samples are invalid") from exc
    if audio.size < math.ceil(sample_rate * MIN_CAPTURE_SECONDS):
        raise CalibrationError("calibration capture is too short")
    if not np.all(np.isfinite(audio)):
        raise CalibrationError("calibration capture contains non-finite samples")

    discard = round(sample_rate * DISCARD_SECONDS)
    window_size = max(2, round(sample_rate * WINDOW_SECONDS))
    usable = audio[discard:]
    window_count = usable.size // window_size
    if window_count < 1:
        raise CalibrationError("calibration capture is too short")
    windows = usable[: window_count * window_size].reshape(window_count, window_size)

    peak = float(np.max(np.abs(windows)))
    if peak == 0.0:
        raise CalibrationError("calibration capture is digital silence")

    # Strongly changing energy usually means speech or an ambient event rather
    # than stationary room noise. Percentiles ignore isolated callback-edge
    # anomalies while rejecting sustained level changes.
    rms = np.sqrt(np.mean(windows * windows, axis=1))
    # A stray all-zero callback window is not enough to invalidate an otherwise
    # stable capture. Sustained zero/nonzero transitions still dominate p10 and
    # trip the spread check below.
    rms_dbfs = 20.0 * np.log10(np.maximum(rms, np.finfo(np.float64).tiny))
    spread = float(np.percentile(rms_dbfs, 90) - np.percentile(rms_dbfs, 10))
    if spread > NONSTATIONARY_SPREAD_DB:
        raise CalibrationError("calibration capture is strongly nonstationary")

    band_windows = np.stack([_band_dbfs(window, sample_rate) for window in windows])
    band_percentiles = np.percentile(band_windows, 95, axis=0)
    loudest = float(np.max(band_percentiles))
    if not math.isfinite(loudest):
        raise CalibrationError("calibration capture is digital silence")

    candidate = loudest + CALIBRATION_HEADROOM_DB
    if candidate > MAX_SPECTRUM_FLOOR_DBFS:
        raise CalibrationError("calibration capture is too loud")
    return float(max(MIN_SPECTRUM_FLOOR_DBFS, math.ceil(candidate)))


def calibrate_spectrum_floor(
    device: str | int | None,
    *,
    on_countdown: Callable[[int], None],
) -> float:
    """Capture room noise from *device* and return its display-only floor.

    ``on_countdown`` receives 3, 2, 1 during the silent countdown and then 0
    immediately before capture starts. The recorder and every returned sample
    buffer are cleared on success, failure, or interruption.
    """
    recorder = Recorder(device=device, max_seconds=CAPTURE_SECONDS)
    captured = np.empty(0, dtype=np.float32)
    try:
        recorder.prepare()
        for remaining in range(COUNTDOWN_SECONDS, 0, -1):
            on_countdown(remaining)
            time.sleep(1.0)
        on_countdown(0)
        recorder.start()
        time.sleep(float(CAPTURE_SECONDS))
        captured = recorder.stop()
        return estimate_spectrum_floor(captured, 16000)
    finally:
        recorder.close()
        captured.fill(0.0)
