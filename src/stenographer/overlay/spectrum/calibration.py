# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
import time
from collections.abc import Callable

import numpy as np

from stenographer.lib.audio.recorder import Recorder
from stenographer.overlay.spectrum.analysis import (
    MAX_SPECTRUM_FLOOR_DBFS,
    MIN_SPECTRUM_FLOOR_DBFS,
    WINDOW_SECONDS,
    _band_dbfs,
)
from stenographer.overlay.spectrum.errors import CalibrationError

COUNTDOWN_SECONDS = 3


CAPTURE_SECONDS = 5


DISCARD_SECONDS = 0.5


MIN_CAPTURE_SECONDS = 4.5


CALIBRATION_HEADROOM_DB = 3.0


NONSTATIONARY_SPREAD_DB = 12.0


_SAMPLE_RATE = 16000


def estimate_spectrum_profile(samples: object) -> tuple[float, ...]:
    """Estimate 18 fixed display floors from a nominal five-second quiet capture.

    The first half-second is discarded. Remaining complete, non-overlapping
    32 ms windows use the same 18-band measurement as the live overlay. Each
    band's 95th percentile receives 3 dB of headroom and is rounded
    upward to a whole dB. No live recording can modify the returned profile.
    """
    try:
        audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("calibration samples are invalid") from exc
    if audio.size < math.ceil(_SAMPLE_RATE * MIN_CAPTURE_SECONDS):
        raise CalibrationError("calibration capture is too short")
    if not np.all(np.isfinite(audio)):
        raise CalibrationError("calibration capture contains non-finite samples")

    discard = round(_SAMPLE_RATE * DISCARD_SECONDS)
    window_size = max(2, round(_SAMPLE_RATE * WINDOW_SECONDS))
    usable = audio[discard:]
    window_count = usable.size // window_size
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

    band_windows = np.stack([_band_dbfs(window, _SAMPLE_RATE) for window in windows])
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
    recorder_factory: Callable[..., Recorder] | None = None,
) -> tuple[float, ...]:
    """Capture known silence and return one fixed profile.

    *recorder_factory* defaults to :class:`Recorder` and is called with the same
    ``device``/``max_seconds`` keywords, so tests can supply a substitute capture
    source without a real input device.
    """
    factory = recorder_factory if recorder_factory is not None else Recorder
    recorder = factory(device=device, max_seconds=CAPTURE_SECONDS)
    quiet = np.empty(0, dtype=np.float32)
    try:
        quiet = _record_room_noise(recorder, on_countdown)
        return estimate_spectrum_profile(quiet)
    finally:
        recorder.close()
        quiet.fill(0.0)
