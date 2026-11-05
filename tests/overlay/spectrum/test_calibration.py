# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for one-shot display spectrum calibration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.overlay.spectrum import calibration
from stenographer.overlay.spectrum.calibration import (
    estimate_spectrum_profile,
)
from stenographer.overlay.spectrum.errors import CalibrationError

_RATE = 16000
_SECONDS = 5.0


def _tone(amplitude: float, *, seconds: float = _SECONDS, frequency: float = 1000.0) -> np.ndarray:
    times = np.arange(round(_RATE * seconds), dtype=np.float64) / _RATE
    return (amplitude * np.sin(2.0 * math.pi * frequency * times)).astype(np.float32)


def _estimate_spectrum_floor(samples: object) -> float:
    return max(estimate_spectrum_profile(samples))


def test_estimator_adds_three_db_and_rounds_upward() -> None:
    # An FFT-bin-centered tone measures at its peak amplitude in the dominant band.
    audio = _tone(10.0 ** (-50.2 / 20.0))

    assert _estimate_spectrum_floor(audio) == -47.0


def test_profile_estimator_returns_independent_fixed_band_floors() -> None:
    audio = _tone(10.0 ** (-50.2 / 20.0), frequency=1000.0)

    profile = estimate_spectrum_profile(audio)

    assert len(profile) == SPECTRUM_BANDS
    assert max(profile) == -47.0
    assert min(profile) == -96.0


def test_estimator_discards_the_first_half_second() -> None:
    audio = _tone(10.0 ** (-62.0 / 20.0))
    audio[: round(0.5 * _RATE)] = _tone(0.5, seconds=0.5)

    assert _estimate_spectrum_floor(audio) == -59.0


def test_estimator_uses_bandwise_ninety_fifth_percentiles() -> None:
    audio = _tone(10.0 ** (-55.0 / 20.0))
    window = round(0.032 * _RATE)
    first_analyzed = round(0.5 * _RATE)
    # Fewer than 5% of analyzed windows are louder and therefore do not set p95.
    for index in range(5):
        start = first_analyzed + index * window
        audio[start : start + window] = _tone(10.0 ** (-25.0 / 20.0), seconds=0.032)

    assert _estimate_spectrum_floor(audio) == -52.0


def test_estimator_clamps_an_extremely_quiet_capture_to_minus_ninety_six() -> None:
    assert _estimate_spectrum_floor(_tone(1e-7)) == -96.0


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
        _estimate_spectrum_floor(audio)


def test_estimator_rejects_strongly_nonstationary_capture() -> None:
    audio = _tone(10.0 ** (-60.0 / 20.0))
    midpoint = audio.size // 2
    audio[midpoint:] = _tone(10.0 ** (-35.0 / 20.0), seconds=_SECONDS / 2.0)

    with pytest.raises(CalibrationError, match="nonstationary"):
        _estimate_spectrum_floor(audio)


def test_estimator_tolerates_one_zero_callback_window() -> None:
    audio = _tone(10.0 ** (-55.0 / 20.0))
    window = round(0.032 * _RATE)
    first_analyzed = round(0.5 * _RATE)
    audio[first_analyzed : first_analyzed + window] = 0.0

    assert _estimate_spectrum_floor(audio) == -52.0


def test_estimator_rejects_nonfinite_samples() -> None:
    audio = _tone(0.001)
    audio[100] = np.nan

    with pytest.raises(CalibrationError, match="non-finite"):
        _estimate_spectrum_floor(audio)


class _FakeRecorder:
    """A capture source with the four methods the calibration flow drives."""

    def __init__(
        self,
        capture: np.ndarray,
        *,
        device: object = None,
        max_seconds: object = None,
        log: list[str] | None = None,
    ) -> None:
        self._capture = capture
        self.device = device
        self.max_seconds = max_seconds
        self.calls: list[str] = [] if log is None else log

    def prepare(self) -> None:
        self.calls.append("prepare")

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> np.ndarray:
        self.calls.append("stop")
        return self._capture

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def instant_waits(monkeypatch):
    """Run the real flow at its real durations without standing through them."""
    waits: list[float] = []
    monkeypatch.setattr(calibration.time, "sleep", waits.append)
    return waits


def _recorder_factory(capture: np.ndarray, log: list[str]):
    """Build the ``recorder_factory`` the calibration calls, and expose it."""
    made: list[_FakeRecorder] = []

    def factory(*, device, max_seconds):
        recorder = _FakeRecorder(capture, device=device, max_seconds=max_seconds, log=log)
        made.append(recorder)
        return recorder

    return factory, made


def test_calibration_counts_the_room_down_then_measures_it(instant_waits) -> None:
    quiet = _tone(0.001)
    expected = estimate_spectrum_profile(quiet)
    events: list[str] = []
    factory, made = _recorder_factory(quiet, log=events)

    def on_countdown(remaining: int) -> None:
        events.append(f"countdown:{remaining}")

    profile = calibration.calibrate_spectrum_profile(
        "hw:1,0",
        on_countdown=on_countdown,
        recorder_factory=factory,
    )

    assert profile == expected
    assert len(profile) == SPECTRUM_BANDS
    assert events == [
        "prepare",
        "countdown:3",
        "countdown:2",
        "countdown:1",
        "countdown:0",
        "start",
        "stop",
        "close",
    ]
    assert [recorder.device for recorder in made] == ["hw:1,0"]
    # The recorder's buffer must be sized for the window it is about to record.
    assert calibration.CAPTURE_SECONDS == 5
    assert [recorder.max_seconds for recorder in made] == [calibration.CAPTURE_SECONDS]
    # The capture window was waited out at its shipped length.
    assert instant_waits.count(1.0) == calibration.COUNTDOWN_SECONDS
    assert float(calibration.CAPTURE_SECONDS) in instant_waits


def test_calibration_wipes_the_capture_before_it_returns(instant_waits) -> None:
    """The buffer may not outlive the call: it is microphone audio, and the
    caller was handed only 18 fixed numbers derived from it.
    """
    quiet = _tone(0.001)
    factory, _made = _recorder_factory(quiet, log=[])

    calibration.calibrate_spectrum_profile(
        None,
        on_countdown=lambda remaining: None,
        recorder_factory=factory,
    )

    assert not quiet.any()


def test_a_rejected_room_capture_fails_and_still_closes(instant_waits) -> None:
    quiet = _tone(0.5)
    events: list[str] = []
    factory, _made = _recorder_factory(quiet, log=events)

    with pytest.raises(CalibrationError, match="too loud"):
        calibration.calibrate_spectrum_profile(
            None,
            on_countdown=lambda remaining: None,
            recorder_factory=factory,
        )

    assert events[-1] == "close"
    assert events.count("close") == 1
    assert not quiet.any()
