# SPDX-License-Identifier: GPL-3.0-or-later
"""One-shot calibration for the display-only microphone spectrum floor.

Calibration is deliberately separate from capture gating and transcription. It
records fixed silence and voice samples, analyzes each only after PortAudio has
stopped, and returns a scalar-compatible 18-band profile for the existing
``feedback.spectrum_floor_dbfs`` setting.
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
    display_levels,
)
from stenographer.status import SPECTRUM_BANDS

COUNTDOWN_SECONDS = 3
CAPTURE_SECONDS = 5
DISCARD_SECONDS = 0.5
# PortAudio callbacks and scheduler wakeups do not land exactly on five seconds.
MIN_CAPTURE_SECONDS = 4.5
CALIBRATION_HEADROOM_DB = 3.0
NONSTATIONARY_SPREAD_DB = 12.0
VOICE_CAPTURE_SECONDS = 3
MIN_VOICE_CAPTURE_SECONDS = 2.5
MIN_VOICE_CONTRAST_DB = 6.0
MIN_VISIBLE_LEVEL = 0.25


class CalibrationError(ValueError):
    """The recorded room-noise sample cannot produce a safe display floor."""


def _validate_sample_rate(sample_rate: int) -> None:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("calibration sample rate must be a positive integer")


def estimate_spectrum_profile(samples: object, sample_rate: int) -> tuple[float, ...]:
    """Estimate 18 fixed display floors from a nominal five-second quiet capture.

    The first half-second is discarded. Remaining complete, non-overlapping
    32 ms windows use the same 18-band measurement as the live overlay. Each
    band's 95th percentile receives 3 dB of headroom and is rounded
    upward to a whole dB. No live recording can modify the returned profile.
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

    candidates = band_percentiles + CALIBRATION_HEADROOM_DB
    if float(np.max(candidates)) > MAX_SPECTRUM_FLOOR_DBFS:
        raise CalibrationError("calibration capture is too loud")
    return tuple(
        float(max(MIN_SPECTRUM_FLOOR_DBFS, math.ceil(candidate)))
        if math.isfinite(float(candidate))
        else MIN_SPECTRUM_FLOOR_DBFS
        for candidate in candidates
    )


def estimate_spectrum_floor(samples: object, sample_rate: int) -> float:
    """Return the legacy scalar floor represented by a calibrated profile."""
    return max(estimate_spectrum_profile(samples, sample_rate))


def validate_voice_visibility(
    samples: object,
    sample_rate: int,
    profile: object,
) -> None:
    """Reject a voice sample that the fixed profile would not visibly render."""
    _validate_sample_rate(sample_rate)
    try:
        audio = np.asarray(samples, dtype=np.float64).reshape(-1)
        floors = np.asarray(profile, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("voice validation samples are invalid") from exc
    if audio.size < math.ceil(sample_rate * MIN_VOICE_CAPTURE_SECONDS):
        raise CalibrationError("voice validation capture is too short")
    if not np.all(np.isfinite(audio)):
        raise CalibrationError("voice validation capture contains non-finite samples")
    if floors.size != SPECTRUM_BANDS:
        raise CalibrationError("voice validation profile must contain 18 bands")

    window_size = max(2, round(sample_rate * WINDOW_SECONDS))
    window_count = audio.size // window_size
    windows = audio[: window_count * window_size].reshape(window_count, window_size)
    band_windows = np.stack([_band_dbfs(window, sample_rate) for window in windows])
    mapped = np.stack([display_levels(frame, floors) for frame in band_windows])
    visible = float(np.percentile(np.max(mapped, axis=1), 90))
    contrast = float(np.max(np.percentile(band_windows, 90, axis=0) - floors))
    if visible < MIN_VISIBLE_LEVEL or contrast < MIN_VOICE_CONTRAST_DB:
        raise CalibrationError("voice sample is not clearly above room noise")


def _record_room_noise(recorder: Recorder, on_countdown: Callable[[int], None]) -> np.ndarray:
    """Prepare *recorder*, count the room down to silence, and return the quiet capture.

    ``on_countdown`` receives 3, 2, 1 during the silent countdown and then 0
    immediately before capture starts. Clearing the returned buffer is the
    caller's job, because only the caller knows when it is done with it.
    """
    recorder.prepare()
    for remaining in range(COUNTDOWN_SECONDS, 0, -1):
        on_countdown(remaining)
        time.sleep(1.0)
    on_countdown(0)
    recorder.start()
    time.sleep(float(CAPTURE_SECONDS))
    return recorder.stop()


def calibrate_spectrum_profile(
    device: str | int | None,
    *,
    on_countdown: Callable[[int], None],
    on_voice_prompt: Callable[[], None],
) -> tuple[float, ...]:
    """Capture known silence plus normal voice and return one fixed profile."""
    recorder = Recorder(device=device, max_seconds=CAPTURE_SECONDS)
    quiet = np.empty(0, dtype=np.float32)
    voice = np.empty(0, dtype=np.float32)
    try:
        quiet = _record_room_noise(recorder, on_countdown)
        profile = estimate_spectrum_profile(quiet, 16000)

        on_voice_prompt()
        recorder.start()
        time.sleep(float(VOICE_CAPTURE_SECONDS))
        voice = recorder.stop()
        validate_voice_visibility(voice, 16000, profile)
        return profile
    finally:
        recorder.close()
        quiet.fill(0.0)
        voice.fill(0.0)


def calibrate_spectrum_floor(
    device: str | int | None,
    *,
    on_countdown: Callable[[int], None],
) -> float:
    """Capture room noise from *device* and return its display-only floor.

    The countdown contract is ``_record_room_noise``'s; the recorder and every
    returned sample buffer are cleared on success, failure, or interruption.
    """
    recorder = Recorder(device=device, max_seconds=CAPTURE_SECONDS)
    captured = np.empty(0, dtype=np.float32)
    try:
        captured = _record_room_noise(recorder, on_countdown)
        return estimate_spectrum_floor(captured, 16000)
    finally:
        recorder.close()
        captured.fill(0.0)
