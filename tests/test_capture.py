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
    assert kwargs["channels"] == 2
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


def test_audio_observer_can_request_a_faster_callback_cadence() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=1024,
            device=None,
            on_error=_noop,
            on_audio=lambda _samples, _rate: None,
            max_audio_observer_interval_seconds=1.0 / 60.0,
        )
        r.start()
    assert patched.call_args.kwargs["blocksize"] == 266
    r.stop()


def test_audio_observer_cadence_does_not_enlarge_configured_blocks() -> None:
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=128,
            device=None,
            on_error=_noop,
            on_audio=lambda _samples, _rate: None,
            max_audio_observer_interval_seconds=1.0 / 60.0,
        )
        r.start()
    assert patched.call_args.kwargs["blocksize"] == 128
    r.stop()


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


def test_callback_publishes_mono_audio_at_actual_sample_rate() -> None:
    observed: list[tuple[np.ndarray, int]] = []
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=4,
            device=None,
            on_error=_noop,
            on_audio=lambda samples, rate: observed.append((samples.copy(), rate)),
        )
        r.start()
    stereo = np.array(
        [[0.1, 0.9], [0.2, 0.8], [0.3, 0.7], [0.4, 0.6]],
        dtype=np.float32,
    )
    r._on_audio(stereo, 4, None, None)
    r.stop()
    assert len(observed) == 1
    assert observed[0][1] == 16000
    assert np.allclose(observed[0][0], stereo[:, 0])


def test_callback_ignores_audio_observer_failure() -> None:
    def fail(_samples: np.ndarray, _rate: int) -> None:
        raise RuntimeError("visualizer failed")

    with patch("sounddevice.InputStream", MagicMock()):
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=4,
            device=None,
            on_error=_noop,
            on_audio=fail,
        )
        r.start()
    r._on_audio(np.ones((4, 1), dtype=np.float32), 4, None, None)
    assert r.stop().shape == (4, 1)


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


def test_start_falls_back_on_invalid_sample_rate() -> None:
    fake_stream = MagicMock()
    with patch(
        "sounddevice.InputStream",
        side_effect=[
            sounddevice.PortAudioError("Invalid sample rate", -9997),
            fake_stream,
        ],
    ) as patched:
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        r.start()
    assert patched.call_count == 2
    assert patched.call_args_list[0].kwargs["samplerate"] == 16000
    assert patched.call_args_list[1].kwargs["samplerate"] == 48000
    assert r._sample_rate == 48000
    assert r.is_active is True
    r.stop()


def test_start_does_not_fallback_on_non_rate_error() -> None:
    with patch(
        "sounddevice.InputStream",
        side_effect=sounddevice.PortAudioError("Invalid device", -9996),
    ):
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        with pytest.raises(sounddevice.PortAudioError):
            r.start()
    assert r.is_active is False


def test_start_raises_when_all_rates_rejected() -> None:
    with patch(
        "sounddevice.InputStream",
        side_effect=sounddevice.PortAudioError("Invalid sample rate", -9997),
    ):
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        with pytest.raises(sounddevice.PortAudioError):
            r.start()
    assert r.is_active is False


def test_start_uses_configured_rate_when_accepted() -> None:
    errors: list[Exception] = []

    def collect(exc: Exception) -> None:
        errors.append(exc)

    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream) as patched:
        r = Recorder(sample_rate=44100, frames_per_buffer=1024, device=None, on_error=collect)
        r.start()
    assert patched.call_count == 1
    assert patched.call_args.kwargs["samplerate"] == 44100
    assert r._sample_rate == 44100
    assert errors == []
    r.stop()


def test_stop_resamples_fallback_buffer_to_configured_rate() -> None:
    """If the device opens at a non-configured rate via the fallback loop,
    stop() MUST return a buffer resampled to cfg.audio.sample_rate so the
    ASR model gets samples at its expected 16 kHz."""
    fake_stream = MagicMock()
    with patch(
        "sounddevice.InputStream",
        side_effect=[
            sounddevice.PortAudioError("Invalid sample rate", -9997),
            fake_stream,
        ],
    ) as patched:
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        r.start()
    assert patched.call_args_list[1].kwargs["samplerate"] == 48000
    assert r._sample_rate == 48000
    # Feed ~1s of 48 kHz mono (sine) into the callback.
    n_in = 48000
    t = np.arange(n_in, dtype=np.float32) / 48000
    block = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(-1, 1)
    r._on_audio(block, n_in, None, None)
    out = r.stop()
    assert out.dtype == np.float32
    assert out.ndim == 2
    assert out.shape[1] == 1
    # ~1s at 16 kHz (filter tail adds a handful of samples; allow slack).
    assert 15700 <= out.shape[0] <= 16500
    # Energy should survive the anti-aliased downsample (no silent / aliased output).
    assert float(np.sqrt(np.mean(out[:, 0] ** 2))) > 0.1


def test_stop_no_resample_when_device_opened_at_configured_rate() -> None:
    """Happy path (PipeWire default opens 16 kHz without fallback): stop()
    MUST NOT resample — the buffer must pass through byte-identical in length."""
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        r.start()
    assert r._sample_rate == 16000
    frames = 1024
    r._on_audio(np.ones((frames, 1), dtype=np.float32), frames, None, None)
    out = r.stop()
    assert out.shape == (frames, 1)
    assert np.allclose(out[:, 0], 1.0)


# ---------------------------------------------------------------------------
# Silence-based mid-recording flush
# ---------------------------------------------------------------------------


def _silence_recorder(
    segments: list[np.ndarray],
    *,
    silence_duration_seconds: float = 1.5,
    sample_rate: int = 16000,
) -> Recorder:
    """A started Recorder with silence detection on and its flush callback
    wired to append into ``segments``. Uses the mocked InputStream."""
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(
            sample_rate=sample_rate,
            frames_per_buffer=1024,
            device=None,
            on_error=_noop,
            silence_detection=True,
            silence_rms_threshold=0.01,
            silence_duration_seconds=silence_duration_seconds,
        )
        r.start(on_segment=segments.append)
    return r


def _speech(n: int, amp: float = 0.2) -> np.ndarray:
    return np.full((n, 1), amp, dtype=np.float32)


def _silent(n: int) -> np.ndarray:
    return np.zeros((n, 1), dtype=np.float32)


def test_silence_detection_flushes_segment_on_pause() -> None:
    segments: list[np.ndarray] = []
    r = _silence_recorder(segments)
    n = 8000  # 0.5 s at 16 kHz; speech >= 0.25 s so _seen_speech is set
    r._on_audio(_speech(n), n, None, None)  # speech
    r._on_audio(_silent(n), n, None, None)  # silence 0.5 s
    r._on_audio(_silent(n), n, None, None)  # silence 1.0 s
    assert segments == []  # 1.0 s < 1.5 s threshold, no flush yet
    r._on_audio(_silent(n), n, None, None)  # silence 1.5 s -> flush
    assert len(segments) == 1
    assert segments[0].shape == (4 * n, 1)  # speech + 3 silence blocks
    # Buffer was reset; nothing but silence remains, so the tail is dropped.
    assert r.stop().shape[0] == 0


def test_silence_detection_ignores_pure_silence() -> None:
    segments: list[np.ndarray] = []
    r = _silence_recorder(segments)
    n = 8000
    for _ in range(10):  # 5 s of silence, never any speech
        r._on_audio(_silent(n), n, None, None)
    assert segments == []
    # No flush ever happened, so stop() returns the whole (silent) buffer.
    assert r.stop().shape[0] == 10 * n


def test_silence_detection_ignores_short_click() -> None:
    segments: list[np.ndarray] = []
    r = _silence_recorder(segments)
    # 1000 frames of speech = 0.0625 s < the 0.25 s minimum, then a long pause.
    r._on_audio(_speech(1000, amp=0.5), 1000, None, None)
    for _ in range(4):
        r._on_audio(_silent(8000), 8000, None, None)  # 2 s of silence
    assert segments == []


def test_silence_detection_flushes_each_pause_in_order() -> None:
    segments: list[np.ndarray] = []
    r = _silence_recorder(segments)
    n = 8000
    r._on_audio(_speech(n, amp=0.2), n, None, None)
    for _ in range(3):
        r._on_audio(_silent(n), n, None, None)  # flush 1
    r._on_audio(_speech(n, amp=0.5), n, None, None)
    for _ in range(3):
        r._on_audio(_silent(n), n, None, None)  # flush 2
    assert len(segments) == 2
    assert np.isclose(np.abs(segments[0][:, 0]).max(), 0.2)
    assert np.isclose(np.abs(segments[1][:, 0]).max(), 0.5)


def test_silence_detection_disabled_returns_whole_buffer() -> None:
    segments: list[np.ndarray] = []
    fake_stream = MagicMock()
    with patch("sounddevice.InputStream", fake_stream):
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=1024,
            device=None,
            on_error=_noop,
            silence_detection=False,
        )
        r.start(on_segment=segments.append)
    n = 8000
    r._on_audio(_speech(n), n, None, None)
    for _ in range(5):
        r._on_audio(_silent(n), n, None, None)
    assert segments == []  # detection off: no flush
    assert r.stop().shape[0] == 6 * n  # entire recording returned


def test_stop_returns_tail_speech_after_flush() -> None:
    segments: list[np.ndarray] = []
    r = _silence_recorder(segments)
    n = 8000
    r._on_audio(_speech(n, amp=0.2), n, None, None)
    for _ in range(3):
        r._on_audio(_silent(n), n, None, None)  # flush
    assert len(segments) == 1
    # New speech after the flush must be returned by stop(), not dropped.
    r._on_audio(_speech(n, amp=0.3), n, None, None)
    out = r.stop()
    assert out.shape == (n, 1)
    assert np.allclose(out[:, 0], 0.3)


def test_silence_flush_resamples_fallback_rate() -> None:
    segments: list[np.ndarray] = []
    fake_stream = MagicMock()
    with patch(
        "sounddevice.InputStream",
        side_effect=[
            sounddevice.PortAudioError("Invalid sample rate", -9997),
            fake_stream,
        ],
    ):
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=1024,
            device=None,
            on_error=_noop,
            silence_detection=True,
            silence_rms_threshold=0.01,
            silence_duration_seconds=0.5,
        )
        r.start(on_segment=segments.append)
    assert r._sample_rate == 48000  # fell back
    n = 48000  # 1 s at the device rate
    t = np.arange(n, dtype=np.float32) / 48000
    speech = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(-1, 1)
    r._on_audio(speech, n, None, None)  # 1 s speech
    r._on_audio(_silent(n), n, None, None)  # 1 s silence >= 0.5 s -> flush
    assert len(segments) == 1
    # 2 s captured at 48 kHz, flushed and resampled to ~2 s at 16 kHz.
    assert 31000 <= segments[0].shape[0] <= 33000
    assert segments[0].dtype == np.float32


def test_resample_poly_identity_and_empty() -> None:
    from stenographer.audio.capture import _resample_poly

    x = np.linspace(-1, 1, 100, dtype=np.float32)
    assert np.array_equal(_resample_poly(x, 16000, 16000), x)
    assert _resample_poly(np.zeros(0, dtype=np.float32), 48000, 16000).shape == (0,)


def test_resample_poly_downsamples_48k_to_16k_without_aliasing() -> None:
    from stenographer.audio.capture import _resample_poly

    sr_in, sr_out = 48000, 16000
    t = np.arange(sr_in, dtype=np.float32) / sr_in
    x = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    y = _resample_poly(x, sr_in, sr_out)
    assert y.dtype == np.float32
    # ~1s at the target rate.
    assert 15700 <= y.size <= 16500
    # Anti-aliased: RMS at the output must be close to the input RMS.
    assert abs(float(np.sqrt(np.mean(x**2))) - float(np.sqrt(np.mean(y**2)))) < 0.02


# --- on_partial / snapshot (live streaming) ---


def _partial_recorder(min_partial_seconds: float = 1.0) -> tuple[Recorder, list[int]]:
    fires: list[int] = []
    with patch("sounddevice.InputStream", MagicMock()):
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        r.start(on_partial=lambda: fires.append(1), min_partial_seconds=min_partial_seconds)
    return r, fires


def test_on_partial_fires_only_after_min_partial_seconds() -> None:
    r, fires = _partial_recorder(min_partial_seconds=1.0)
    block = np.zeros((8000, 1), dtype=np.float32)  # 0.5 s at 16 kHz
    r._on_audio(block, 8000, None, None)
    assert fires == []
    r._on_audio(block, 8000, None, None)  # cumulative 1.0 s -> fire
    assert fires == [1]
    r._on_audio(block, 8000, None, None)  # counter reset: 0.5 s again
    assert fires == [1]
    r._on_audio(block, 8000, None, None)
    assert fires == [1, 1]


def test_on_partial_stops_after_cap() -> None:
    fires: list[int] = []
    with patch("sounddevice.InputStream", MagicMock()):
        r = Recorder(
            sample_rate=16000,
            frames_per_buffer=1024,
            device=None,
            on_error=_noop,
            max_seconds=1,
        )
        r.start(on_partial=lambda: fires.append(1), min_partial_seconds=1.0)
    block = np.zeros((16000, 1), dtype=np.float32)  # exactly the 1 s cap
    r._on_audio(block, 16000, None, None)
    assert fires == [1]
    r._on_audio(block, 16000, None, None)  # capped: no append, no partial
    assert fires == [1]


def test_on_partial_and_on_segment_mutually_exclusive() -> None:
    with patch("sounddevice.InputStream", MagicMock()):
        r = Recorder(sample_rate=16000, frames_per_buffer=1024, device=None, on_error=_noop)
        with pytest.raises(ValueError):
            r.start(on_segment=lambda arr: None, on_partial=lambda: None)


def test_snapshot_full_buffer_matches_finalize() -> None:
    r, _fires = _partial_recorder()
    block = np.linspace(0, 1, 16000, dtype=np.float32).reshape(-1, 1)
    r._on_audio(block, 16000, None, None)
    snap = r.snapshot(0.0)
    assert snap.shape == (16000, 1)
    assert np.array_equal(snap, block)


def test_snapshot_slices_from_start_seconds() -> None:
    r, _fires = _partial_recorder()
    block = np.arange(16000, dtype=np.float32).reshape(-1, 1)
    r._on_audio(block, 16000, None, None)
    snap = r.snapshot(0.5)
    assert snap.shape == (8000, 1)
    assert snap[0, 0] == 8000.0  # element at 0.5 s


def test_snapshot_resamples_when_device_rate_differs() -> None:
    r, _fires = _partial_recorder()
    r._sample_rate = 48000  # simulate a device fallback (configured 16 kHz)
    block = np.zeros((48000, 1), dtype=np.float32)  # 1 s at device rate
    r._on_audio(block, 48000, None, None)
    snap = r.snapshot(0.5)
    # 0.5 s remaining, resampled to the configured 16 kHz.
    assert abs(snap.shape[0] - 8000) <= 50


def test_snapshot_after_stop_returns_empty() -> None:
    r, _fires = _partial_recorder()
    r._on_audio(np.zeros((16000, 1), dtype=np.float32), 16000, None, None)
    r.stop()
    assert r.snapshot(0.0).shape == (0, 1)
