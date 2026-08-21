# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for one-shot display spectrum calibration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stenographer.cli.calibration import (
    CalibrationError,
    estimate_spectrum_floor,
)

_RATE = 16000
_SECONDS = 5.0


def _tone(amplitude: float, *, seconds: float = _SECONDS, frequency: float = 1000.0) -> np.ndarray:
    times = np.arange(round(_RATE * seconds), dtype=np.float64) / _RATE
    return (amplitude * np.sin(2.0 * math.pi * frequency * times)).astype(np.float32)


def test_estimator_adds_three_db_and_rounds_upward() -> None:
    # An FFT-bin-centered tone measures at its peak amplitude in the dominant band.
    audio = _tone(10.0 ** (-50.2 / 20.0))

    assert estimate_spectrum_floor(audio, _RATE) == -47.0


def test_estimator_discards_the_first_half_second() -> None:
    audio = _tone(10.0 ** (-62.0 / 20.0))
    audio[: round(0.5 * _RATE)] = _tone(0.5, seconds=0.5)

    assert estimate_spectrum_floor(audio, _RATE) == -59.0


def test_estimator_uses_bandwise_ninety_fifth_percentiles() -> None:
    audio = _tone(10.0 ** (-55.0 / 20.0))
    window = round(0.032 * _RATE)
    first_analyzed = round(0.5 * _RATE)
    # Fewer than 5% of analyzed windows are louder and therefore do not set p95.
    for index in range(5):
        start = first_analyzed + index * window
        audio[start : start + window] = _tone(10.0 ** (-25.0 / 20.0), seconds=0.032)

    assert estimate_spectrum_floor(audio, _RATE) == -52.0


def test_estimator_clamps_an_extremely_quiet_capture_to_minus_ninety_six() -> None:
    assert estimate_spectrum_floor(_tone(1e-7), _RATE) == -96.0


@pytest.mark.parametrize(
    ("audio", "message"),
    [
        (np.zeros(round(_RATE * _SECONDS), dtype=np.float32), "digital silence"),
        (_tone(0.5), "too loud"),
        (_tone(0.001, seconds=1.0), "too short"),
    ],
)
def test_estimator_rejects_unusable_captures(audio: np.ndarray, message: str) -> None:
    with pytest.raises(CalibrationError, match=message):
        estimate_spectrum_floor(audio, _RATE)


def test_estimator_rejects_strongly_nonstationary_capture() -> None:
    audio = _tone(10.0 ** (-60.0 / 20.0))
    midpoint = audio.size // 2
    audio[midpoint:] = _tone(10.0 ** (-35.0 / 20.0), seconds=_SECONDS / 2.0)

    with pytest.raises(CalibrationError, match="nonstationary"):
        estimate_spectrum_floor(audio, _RATE)


def test_estimator_tolerates_one_zero_callback_window() -> None:
    audio = _tone(10.0 ** (-55.0 / 20.0))
    window = round(0.032 * _RATE)
    first_analyzed = round(0.5 * _RATE)
    audio[first_analyzed : first_analyzed + window] = 0.0

    assert estimate_spectrum_floor(audio, _RATE) == -52.0


@pytest.mark.parametrize("sample_rate", [0, -1, 16000.0, True])
def test_estimator_rejects_invalid_sample_rates(sample_rate: object) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        estimate_spectrum_floor(_tone(0.001), sample_rate)  # type: ignore[arg-type]


def test_estimator_rejects_nonfinite_samples() -> None:
    audio = _tone(0.001)
    audio[100] = np.nan

    with pytest.raises(CalibrationError, match="non-finite"):
        estimate_spectrum_floor(audio, _RATE)
