# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.audio.capture`."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sounddevice

from stenographer.audio.capture import Recorder


def _noop(_exc: Exception) -> None:
    return None


def test_recorder_is_inactive_after_init() -> None:
    r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
    assert r.is_active is False


def test_start_opens_input_stream_with_expected_kwargs() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        r.start()
    assert patched.call_count == 1
    kwargs = patched.call_args.kwargs
    assert kwargs["samplerate"] == 16000
    assert kwargs["channels"] == 1
    assert kwargs["dtype"] == "float32"
    assert kwargs["blocksize"] == 1024
    assert kwargs["device"] is None
    assert callable(kwargs["callback"])
    returned_stream = patched.return_value
    returned_stream.start.assert_called_once()
    assert r.is_active is True
    r.stop()
    returned_stream.stop.assert_called_once()
    returned_stream.close.assert_called_once()


def test_start_normalizes_empty_string_device_to_none() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device="", on_error=_noop)
        r.start()
    assert patched.call_args.kwargs["device"] is None
    r.stop()


def test_start_passes_int_device_through() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=3, on_error=_noop)
        r.start()
    assert patched.call_args.kwargs["device"] == 3
    r.stop()


def test_start_passes_named_device_through() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=1024,
            device="USB Microphone",
            on_error=_noop,
        )
        r.start()
    assert patched.call_args.kwargs["device"] == "USB Microphone"
    r.stop()


def test_callback_accumulates_samples_and_stop_returns_2d_float32() -> None:
    fake_stream = MagicMock()
    frames = 1024
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(sample_rate=16000, frames_per_buffer=frames, device=None, on_error=_noop)
        r.start()
    r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, None)
    r._on_audio(np.zeros((frames, 1), dtype=np.float32), frames, None, None)
    arr = r.stop()
    assert arr.shape == (2 * frames, 1)
    assert arr.dtype == np.float32
    assert np.allclose(arr[:frames, 0], 1.0)
    assert np.allclose(arr[frames:, 0], 0.0)
    assert r.is_active is False


def test_input_overflow_calls_on_error_exactly_once_on_stop() -> None:
    fake_stream = MagicMock()
    errors: list[Exception] = []

    def collect(exc: Exception) -> None:
        errors.append(exc)

    frames = 1024
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(sample_rate=16000, frames_per_buffer=frames, device=None, on_error=collect)
        r.start()
    status = sounddevice.CallbackFlags()
    status.input_overflow = True
    r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, status)
    r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, status)
    r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, status)
    r.stop()
    assert len(errors) == 1


def test_no_overflow_does_not_invoke_on_error() -> None:
    fake_stream = MagicMock()
    errors: list[Exception] = []

    def collect(exc: Exception) -> None:
        errors.append(exc)

    frames = 1024
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(sample_rate=16000, frames_per_buffer=frames, device=None, on_error=collect)
        r.start()
    r._on_audio(np.zeros((frames, 1), dtype=np.float32), frames, None, None)
    r.stop()
    assert errors == []


def test_recorder_is_reusable_across_start_stop_cycles() -> None:
    fake_stream = MagicMock()
    frames = 512
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(sample_rate=16000, frames_per_buffer=frames, device=None, on_error=_noop)
        r.start()
        r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, None)
        first = r.stop()
        assert first.shape == (frames, 1)
        r.start()
        r._on_audio(np.full((frames, 1), 0.5, dtype=np.float32), frames, None, None)
        second = r.stop()
    assert second.shape == (frames, 1)
    assert np.allclose(second[:, 0], 0.5)
    assert not np.allclose(first[:, 0], second[:, 0])


def test_default_input_device_name_returns_name() -> None:
    info = {"name": "Test Mic", "index": 0, "max_input_channels": 1}
    with patch("sounddevice.query_devices", return_value=info):
        assert Recorder.default_input_device_name() == "Test Mic"


def test_default_input_device_name_returns_none_on_portaudio_error() -> None:
    with patch(
        "sounddevice.query_devices",
        side_effect=sounddevice.PortAudioError("no device"),
    ):
        assert Recorder.default_input_device_name() is None


def test_default_input_device_name_returns_none_when_dict_empty() -> None:
    with patch("sounddevice.query_devices", return_value={}):
        assert Recorder.default_input_device_name() is None


@pytest.mark.integration
def test_real_audio_recording_returns_well_shaped_buffer() -> None:
    try:
        info = sounddevice.query_devices(kind="input")
    except sounddevice.PortAudioError as e:
        pytest.skip(f"PortAudio unavailable: {e}")
    if not info:
        pytest.skip("no default input device detected")
    rate = int(info.get("default_samplerate") or 48000)
    frames = 1024
    try:
        r = Recorder(sample_rate=rate, frames_per_buffer=frames, device=None, on_error=_noop)
        r.start()
    except sounddevice.PortAudioError as e:
        pytest.skip(f"cannot open input stream at {rate} Hz: {e}")
    try:
        time.sleep(0.3)
    finally:
        arr = r.stop()
    assert arr.dtype == np.float32
    assert arr.ndim == 2
    assert arr.shape[1] == 1
    n = arr.shape[0]
    min_samples = int(0.2 * rate)
    max_samples = int(1.0 * rate)
    assert min_samples <= n <= max_samples, (
        f"expected between {min_samples} and {max_samples} samples at {rate} Hz; got {n}"
    )
