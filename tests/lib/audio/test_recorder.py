# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture configuration, the RMS gate, resampling, and the stream lifecycle.

Constructing a ``Recorder`` is pure. ``prepare``, ``_select_default_device``
and ``_negotiate`` all take the ``sounddevice`` module as a parameter, and
``prepare`` remembers it, so preparation, negotiation, the state machine,
stream recovery, the callback and finalization all run here against a stand-in
module that opens no device — no PortAudio symbol is patched anywhere. Only the
real ``import sounddevice`` statement itself (recorder.py:99-101) stays with the
integration smoke suite, along with everything downstream of a genuine PortAudio
stream.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.audio.gate import speech_gate_stats
from stenographer.lib.audio.recorder import (
    _ERR_BAD_CHANNELS,
    _ERR_BAD_SAMPLE_RATE,
    Recorder,
)
from stenographer.lib.audio.resample import _resample_poly
from stenographer.lib.audio.state import RecorderState

_LOGGER = "stenographer.lib.audio.recorder"

_RATE = 16000
_FRAME = int(_RATE * 0.050)  # 800 samples per 50 ms gate frame


def _signal(frame_amplitudes: list[float]) -> np.ndarray:
    """Build audio whose i-th 50 ms frame is a constant at the given amplitude."""
    return np.concatenate([np.full(_FRAME, amp, dtype=np.float32) for amp in frame_amplitudes])


@pytest.mark.parametrize(
    ("configured", "normalized"),
    [
        (None, None),
        ("", None),
        (0, 0),
        (7, 7),
        ("0", 0),
        ("17", 17),
        ("0017", 17),
        ("USB microphone", "USB microphone"),
        ("-1", "-1"),
        ("+1", "+1"),
        (" 1", " 1"),
        ("1 ", "1 "),
        ("1.0", "1.0"),
    ],
)
def test_recorder_normalizes_only_exact_nonnegative_decimal_device_strings(configured, normalized):
    recorder = Recorder(device=configured, max_seconds=2)

    assert recorder._configured_device == normalized
    assert recorder._selected_device == normalized


def test_gate_disabled_passes_silence():
    silence = np.zeros(_RATE, dtype=np.float32)
    assert speech_gate_stats(silence, _RATE, 0.0).passed is True


def test_gate_rejects_pure_silence():
    silence = np.zeros(_RATE, dtype=np.float32)
    assert speech_gate_stats(silence, _RATE, 0.0005).passed is False


def test_gate_rejects_isolated_loud_frame():
    # One loud frame surrounded by silence: no two consecutive loud frames.
    audio = _signal([0.0, 0.0, 0.02, 0.0, 0.0])
    assert speech_gate_stats(audio, _RATE, 0.0005).passed is False


def test_gate_passes_two_consecutive_loud_frames():
    audio = _signal([0.0, 0.02, 0.02, 0.0])
    assert speech_gate_stats(audio, _RATE, 0.0005).passed is True


def test_gate_passes_quiet_mic_speech():
    # RMS ~0.001 sustained speech clears the 0.0005 default the owner relies on.
    audio = _signal([0.001] * 10)
    assert speech_gate_stats(audio, _RATE, 0.0005).passed is True


def test_gate_rejects_speech_below_threshold():
    audio = _signal([0.001] * 10)
    assert speech_gate_stats(audio, _RATE, 0.01).passed is False


def test_gate_rejects_too_short_for_two_frames():
    # Fewer than two whole frames can never satisfy the consecutive rule.
    loud = np.full(_FRAME, 0.02, dtype=np.float32)
    assert speech_gate_stats(loud, _RATE, 0.0005).passed is False


def test_resample_identity_when_rates_match():
    data = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    out = _resample_poly(data, _RATE, _RATE)
    assert np.array_equal(out, data)


def test_resample_empty_stays_empty():
    out = _resample_poly(np.empty(0, dtype=np.float32), 48000, 16000)
    assert out.size == 0


def test_resample_downsample_length_and_dtype():
    data = np.zeros(4800, dtype=np.float32)
    out = _resample_poly(data, 48000, 16000)
    assert out.dtype == np.float32
    # 3:1 decimation of 4800 samples lands near 1600 (plus the FIR tail).
    assert abs(out.size - 1600) <= 40


def test_resample_upsample_length():
    data = np.zeros(800, dtype=np.float32)
    out = _resample_poly(data, 8000, 16000)
    assert abs(out.size - 1600) <= 40


def test_resample_preserves_dc_level():
    data = np.full(4800, 0.3, dtype=np.float32)
    out = _resample_poly(data, 48000, 16000)
    interior = out[100:-100]
    assert interior.size > 0
    assert np.allclose(interior, 0.3, atol=0.02)


@pytest.mark.parametrize("min_rms", [0.0, -1.0])
def test_gate_nonpositive_threshold_disables(min_rms):
    silence = np.zeros(_RATE, dtype=np.float32)
    assert speech_gate_stats(silence, _RATE, min_rms).passed is True


def test_gate_stats_report_the_quiet_mic_rejection_it_decided():
    # The quiet-mic case: speech at RMS 0.001 against a 0.01 threshold. The
    # reported numbers have to be the ones the verdict was reached from, or the
    # log cannot tell a mis-set threshold from a dead microphone. Seen to FAIL
    # against a ``speech_gate_stats`` that counted frames above a hardcoded
    # 0.0005 instead of the threshold it was given (frames_above became 10).
    stats = speech_gate_stats(_signal([0.001] * 10), _RATE, 0.01)

    assert stats.passed is False
    assert stats.frames_above == 0
    assert stats.frames_total == 10
    assert stats.threshold == 0.01
    assert stats.peak_rms == pytest.approx(0.001, abs=1e-6)
    assert stats.mean_rms == pytest.approx(0.001, abs=1e-6)


def test_gate_stats_count_every_loud_frame_not_just_the_consecutive_pair():
    # Three loud frames, only the last two consecutive. The verdict comes from
    # the consecutive rule; the count is of every frame over the threshold, so
    # a near-miss capture is visible as "loud frames, but scattered".
    stats = speech_gate_stats(_signal([0.02, 0.0, 0.02, 0.02, 0.0]), _RATE, 0.0005)

    assert stats.passed is True
    assert stats.frames_above == 3
    assert stats.frames_total == 5
    assert stats.peak_rms == pytest.approx(0.02, abs=1e-6)


def test_gate_stats_on_audio_too_short_to_frame():
    stats = speech_gate_stats(np.empty(0, dtype=np.float32), _RATE, 0.0005)

    assert stats.frames_total == 0
    assert stats.frames_above == 0
    assert stats.peak_rms == 0.0
    assert stats.passed is False


class FakePortAudioError(Exception):
    """PortAudio's error type: ``(message, code)`` args the recorder reads."""


class FakeStream:
    """A negotiated input stream that records its lifecycle instead of opening one."""

    def __init__(
        self, *, samplerate: int, channels: int, callback, start_error: Exception | None = None
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.callback = callback
        self.active = False
        self.stops = 0
        self.closes = 0
        self.start_error = start_error
        self.stop_error: Exception | None = None
        self.close_error: Exception | None = None

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.active = True

    def stop(self, ignore_errors: bool = False) -> None:
        self.stops += 1
        if self.stop_error is not None:
            raise self.stop_error
        self.active = False

    def close(self, ignore_errors: bool = False) -> None:
        self.closes += 1
        self.active = False
        if self.close_error is not None:
            raise self.close_error


class FakeSoundDevice:
    """The ``sounddevice`` module surface the recorder negotiates against."""

    PortAudioError = FakePortAudioError

    def __init__(
        self,
        *,
        reject=None,
        default_index: int = 3,
        name: str = "Fake USB microphone",
        name_error: Exception | None = None,
        stream_start_error: Exception | None = None,
    ) -> None:
        self._reject = reject if reject is not None else (lambda rate, channels: None)
        self._stream_start_error = stream_start_error
        self._default_index = default_index
        self._name = name
        self._name_error = name_error
        self.attempts: list[tuple[int, int, object]] = []
        self.queries: list[tuple[object, object]] = []
        self.streams: list[FakeStream] = []

    def query_devices(self, device=None, kind=None):
        self.queries.append((device, kind))
        if device is None:
            return {"index": self._default_index, "name": self._name}
        if self._name_error is not None:
            raise self._name_error
        return {"index": device, "name": self._name}

    def InputStream(self, *, samplerate, channels, dtype, device, callback):  # noqa: N802
        self.attempts.append((samplerate, channels, device))
        assert dtype == "float32"
        code = self._reject(samplerate, channels)
        if code is not None:
            raise FakePortAudioError("Invalid device parameters", code)
        stream = FakeStream(
            samplerate=samplerate,
            channels=channels,
            callback=callback,
            start_error=self._stream_start_error,
        )
        self.streams.append(stream)
        return stream


def _only(rate: int | None = None, channels: int | None = None):
    """Reject everything but the given rate/channel count, the way a device does."""

    def reject(requested_rate: int, requested_channels: int) -> int | None:
        if channels is not None and requested_channels != channels:
            return _ERR_BAD_CHANNELS
        if rate is not None and requested_rate != rate:
            return _ERR_BAD_SAMPLE_RATE
        return None

    return reject


def _prepared(sounddevice: FakeSoundDevice, **kwargs) -> Recorder:
    recorder = Recorder(**{"device": 1, "max_seconds": 5, **kwargs})
    recorder.prepare(sounddevice)
    return recorder


def _warnings(caplog) -> list[str]:
    """Only the warnings: DEBUG activity is not part of the reporting contract."""
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]


def _feed(recorder: Recorder, block: np.ndarray, *, adc: float = 0.0, overflow: bool = False):
    """Deliver one callback the way PortAudio does: always ``(frames, channels)``."""
    indata = block.reshape(-1, 1) if block.ndim == 1 else block
    recorder._on_audio(
        indata,
        indata.shape[0],
        SimpleNamespace(inputBufferAdcTime=adc),
        SimpleNamespace(input_overflow=overflow),
    )


def test_the_default_input_device_is_resolved_only_when_none_is_configured():
    sounddevice = FakeSoundDevice(default_index=3)
    recorder = Recorder(device=None, max_seconds=5)

    recorder._select_default_device(sounddevice)

    assert recorder._selected_device == 3
    assert sounddevice.queries == [(None, "input")]


def test_a_configured_device_is_never_replaced_by_the_host_default():
    sounddevice = FakeSoundDevice(default_index=3)
    recorder = Recorder(device=7, max_seconds=5)

    recorder._select_default_device(sounddevice)

    assert recorder._selected_device == 7
    assert sounddevice.queries == []


def test_negotiation_asks_for_the_asr_rate_first_and_retains_a_stopped_stream():
    sounddevice = FakeSoundDevice()

    recorder = _prepared(sounddevice)

    assert sounddevice.attempts == [(16000, 2, 1)]
    assert recorder.state is RecorderState.PREPARED
    assert recorder.is_prepared is True
    assert recorder.is_active is False
    assert recorder._device_rate == 16000
    assert recorder._channels == 2
    assert recorder._max_frames == 5 * 16000
    assert recorder._device_name == "Fake USB microphone"
    # Prepared means negotiated, not running: no callbacks may arrive yet.
    assert sounddevice.streams[0].active is False


def test_a_rejected_sample_rate_walks_the_fallback_list_and_says_so(caplog):
    sounddevice = FakeSoundDevice(reject=_only(rate=44100))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        recorder = _prepared(sounddevice)

    assert [rate for rate, _channels, _device in sounddevice.attempts] == [16000, 48000, 44100]
    assert recorder._device_rate == 44100
    assert recorder._max_frames == 5 * 44100
    assert _warnings(caplog) == ["recorder: fallback rate_hz=44100 requested_rate_hz=16000"]


def test_a_rejected_channel_count_is_abandoned_without_trying_its_other_rates():
    sounddevice = FakeSoundDevice(reject=_only(channels=1))

    recorder = _prepared(sounddevice)

    # One attempt at stereo is enough to learn the device is mono.
    assert sounddevice.attempts == [(16000, 2, 1), (16000, 1, 1)]
    assert recorder._channels == 1
    assert recorder._device_rate == 16000


def test_an_unrelated_portaudio_error_is_reported_rather_than_retried():
    sounddevice = FakeSoundDevice(reject=lambda rate, channels: -9996)
    recorder = Recorder(device=1, max_seconds=5)

    with pytest.raises(FakePortAudioError):
        recorder.prepare(sounddevice)

    assert len(sounddevice.attempts) == 1
    assert recorder.state is RecorderState.UNPREPARED
    assert recorder._stream is None


def test_a_device_that_rejects_every_combination_raises_its_own_rejection():
    sounddevice = FakeSoundDevice(reject=lambda rate, channels: _ERR_BAD_SAMPLE_RATE)
    recorder = Recorder(device=1, max_seconds=5)

    with pytest.raises(FakePortAudioError) as exc:
        recorder.prepare(sounddevice)

    assert exc.value.args[1] == _ERR_BAD_SAMPLE_RATE
    # Five rates for each of the two channel counts, and nothing retained.
    assert len(sounddevice.attempts) == 10
    assert recorder.state is RecorderState.UNPREPARED
    assert recorder._stream is None


def test_an_unreadable_device_name_does_not_fail_the_negotiation():
    sounddevice = FakeSoundDevice(name_error=FakePortAudioError("no such device"))

    recorder = _prepared(sounddevice)

    assert recorder.is_prepared is True
    assert recorder._device_name is None


def test_start_activates_the_retained_stream_and_refuses_a_second_start():
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)

    recorder.start()

    assert sounddevice.streams[0].active is True
    assert recorder.state is RecorderState.CAPTURING
    assert recorder.is_active is True
    assert recorder.last_capture is None
    with pytest.raises(RuntimeError, match="already capturing"):
        recorder.start()
    assert len(sounddevice.attempts) == 1


def test_a_mono_capture_returns_its_samples_and_the_cost_of_taking_them():
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()

    _feed(recorder, np.full(800, 0.25, dtype=np.float32), adc=1.0)
    _feed(recorder, np.full(400, -0.5, dtype=np.float32), adc=1.05)
    audio = recorder.stop()

    assert audio.dtype == np.float32
    assert audio.size == 1200
    assert audio[0] == pytest.approx(0.25)
    assert audio[-1] == pytest.approx(-0.5)
    stats = recorder.last_capture
    assert stats is not None
    assert stats.input_frames == 1200
    assert stats.output_frames == 1200
    assert stats.input_rate == 16000
    assert stats.channels == 1
    assert stats.device_name == "Fake USB microphone"
    assert stats.callback_count == 2
    assert stats.callback_timing_count == 2
    assert stats.callback_metadata_dropped == 0
    assert stats.overflow is False
    assert stats.capped is False
    assert stats.recovered is False
    assert stats.first_callback_at is not None
    assert stats.activation_to_callback_ms is not None
    assert stats.finalize_ms is not None
    # The stream is stopped and retained for the next press, not closed.
    assert recorder.state is RecorderState.PREPARED
    assert sounddevice.streams[0].stops == 1
    assert sounddevice.streams[0].closes == 0


def test_a_one_dimensional_callback_block_is_still_accepted():
    # Defensive only: a real PortAudio callback always carries a channel axis.
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()

    recorder._on_audio(
        np.full(800, 0.25, dtype=np.float32),
        800,
        SimpleNamespace(inputBufferAdcTime=1.0),
        SimpleNamespace(input_overflow=False),
    )
    audio = recorder.stop()

    assert audio.size == 800
    assert audio[0] == pytest.approx(0.25)


def test_a_stereo_callback_keeps_channel_zero():
    # The second channel of a stereo microphone is routinely silent or out of
    # phase; averaging it into the capture is what the gate then has to find.
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)
    recorder.start()

    _feed(recorder, np.array([[0.5, -0.5], [0.25, -0.25]], dtype=np.float32))
    audio = recorder.stop()

    assert audio.tolist() == [0.5, 0.25]
    assert recorder.last_capture.channels == 2


def test_a_capture_at_a_fallback_rate_is_resampled_to_the_asr_rate():
    sounddevice = FakeSoundDevice(reject=_only(rate=48000, channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()

    _feed(recorder, np.full(4800, 0.3, dtype=np.float32))
    audio = recorder.stop()

    assert abs(audio.size - 1600) <= 40
    stats = recorder.last_capture
    assert stats.input_rate == 48000
    assert stats.input_frames == 4800
    assert stats.output_frames == audio.size


def test_an_input_overflow_is_counted_and_reported(caplog):
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()

    _feed(recorder, np.zeros(800, dtype=np.float32))
    _feed(recorder, np.zeros(800, dtype=np.float32), overflow=True)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        audio = recorder.stop()

    assert audio.size == 1600
    assert recorder.last_capture.overflow is True
    assert recorder.last_capture.overflow_count == 1
    assert _warnings(caplog) == [
        "recorder: input_overflow input_frames=1600 output_frames=1600 capped=0"
    ]


def test_the_cap_stops_buffering_without_ending_the_capture(caplog):
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice, max_seconds=1)
    recorder.start()

    for _ in range(3):
        _feed(recorder, np.zeros(10000, dtype=np.float32))
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        audio = recorder.stop()

    # The third callback arrives after the cap and is dropped, not appended.
    assert audio.size == 20000
    assert recorder.last_capture.capped is True
    assert recorder.last_capture.input_frames == 20000
    assert _warnings(caplog) == ["recorder: capture_capped max_seconds=1 frames=20000"]


def test_the_optional_block_sink_sees_mono_blocks_and_cannot_break_the_capture():
    seen: list[tuple[int, int, int]] = []

    def sink(block, rate, epoch):
        seen.append((block.shape[0], rate, epoch))
        raise RuntimeError("spectrum consumer failed")

    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice, on_block=sink)
    recorder.start()

    _feed(recorder, np.zeros(800, dtype=np.float32))
    _feed(recorder, np.zeros(400, dtype=np.float32))
    audio = recorder.stop()

    assert seen == [(800, 16000, 1), (400, 16000, 1)]
    assert audio.size == 1200


def test_stopping_a_merely_prepared_recorder_returns_no_audio():
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)

    audio = recorder.stop()

    assert audio.size == 0
    assert audio.dtype == np.float32
    assert recorder.state is RecorderState.PREPARED
    assert recorder.last_capture is None
    assert sounddevice.streams[0].stops == 0


def test_a_stream_that_died_during_capture_discards_the_whole_capture(caplog):
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()
    _feed(recorder, np.full(800, 0.25, dtype=np.float32))
    sounddevice.streams[0].active = False

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(RuntimeError):
        recorder.stop()

    # An uncertain capture is never half-delivered: the stream is invalidated
    # and the buffered audio is dropped rather than returned.
    assert recorder.state is RecorderState.UNPREPARED
    assert recorder.last_capture is None
    assert recorder._blocks == []
    assert sounddevice.streams[0].closes == 1
    message = _warnings(caplog)[0]
    assert "recorder: capture_failed" in message
    assert "phase=stop" in message
    assert "input_frames=800" in message


def test_a_failing_stream_stop_also_discards_the_capture(caplog):
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()
    _feed(recorder, np.zeros(800, dtype=np.float32))
    sounddevice.streams[0].stop_error = FakePortAudioError("stream stop failed")

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(FakePortAudioError):
        recorder.stop()

    assert recorder.state is RecorderState.UNPREPARED
    assert recorder.last_capture is None
    assert "phase=stop" in _warnings(caplog)[0]


def test_close_releases_the_stream_and_lets_the_next_press_reselect_a_default():
    sounddevice = FakeSoundDevice(default_index=3)
    recorder = Recorder(device=None, max_seconds=5)
    recorder._select_default_device(sounddevice)
    recorder._negotiate(sounddevice)

    recorder.close()
    recorder.close()

    assert sounddevice.streams[0].closes == 1
    assert recorder.state is RecorderState.UNPREPARED
    assert recorder._stream is None
    # The default may have moved while the daemon was idle.
    assert recorder._selected_device is None


def test_close_keeps_a_configured_device_selected():
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice, device=7)

    recorder.close()

    assert recorder._selected_device == 7


def test_a_failing_close_is_reported_and_swallowed(caplog):
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)
    sounddevice.streams[0].close_error = FakePortAudioError("device already gone")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        recorder.close()

    assert recorder.state is RecorderState.UNPREPARED
    message = _warnings(caplog)[0]
    assert "recorder: close_failed" in message
    assert "error=FakePortAudioError" in message


def test_adc_clock_gaps_are_measured_from_the_callbacks_of_this_activation():
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()

    # 800 frames at 16 kHz is 50 ms of audio; the third callback's ADC stamp
    # jumps a further 200 ms, which is a clock discontinuity, not lost speech.
    _feed(recorder, np.zeros(800, dtype=np.float32), adc=1.00)
    _feed(recorder, np.zeros(800, dtype=np.float32), adc=1.05)
    _feed(recorder, np.zeros(800, dtype=np.float32), adc=1.30)
    recorder.stop()

    stats = recorder.last_capture
    assert stats.adc_discontinuities == 1
    assert stats.max_adc_gap_ms == pytest.approx(200.0, abs=1e-6)
    assert stats.callback_timing_count == 3


def test_a_second_capture_starts_from_a_clean_slate():
    sounddevice = FakeSoundDevice(reject=_only(channels=1))
    recorder = _prepared(sounddevice)
    recorder.start()
    _feed(recorder, np.full(800, 0.25, dtype=np.float32))
    first = recorder.stop()

    recorder.start()
    _feed(recorder, np.full(400, 0.5, dtype=np.float32))
    second = recorder.stop()

    assert first.size == 800
    assert second.size == 400
    assert second[0] == pytest.approx(0.5)
    assert recorder.last_capture.input_frames == 400
    assert recorder.last_capture.callback_count == 1
    # The same negotiated stream served both captures.
    assert len(sounddevice.streams) == 1
    assert sounddevice.streams[0].stops == 2


def test_a_device_whose_name_is_not_text_is_simply_unnamed():
    sounddevice = FakeSoundDevice(name=None)

    recorder = _prepared(sounddevice)

    assert recorder.is_prepared is True
    assert recorder._device_name is None


def test_activation_refuses_to_run_without_a_negotiated_stream():
    recorder = Recorder(device=1, max_seconds=5)

    with pytest.raises(RuntimeError, match="no prepared stream"):
        recorder._activate(recovery="none")

    assert recorder.state is RecorderState.UNPREPARED


def test_a_retained_stream_that_will_not_activate_is_replaced_exactly_once(caplog):
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)
    # The device went away while the stream sat retained between utterances.
    sounddevice.streams[0].start_error = FakePortAudioError("device unavailable")

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        recorder.start()

    assert len(sounddevice.attempts) == 2
    assert len(sounddevice.streams) == 2
    assert sounddevice.streams[0].closes == 1
    assert sounddevice.streams[1].active is True
    assert recorder.state is RecorderState.CAPTURING

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "recorder: activation_failed" in warnings[0]
    assert "retained=1" in warnings[0]
    assert 'error=FakePortAudioError detail="device unavailable"' in warnings[0]
    activations = [
        record.getMessage()
        for record in caplog.records
        if "recorder: activated" in record.getMessage()
    ]
    assert len(activations) == 1
    assert "recovery=renegotiated" in activations[0]

    _feed(recorder, np.full((800, 2), 0.25, dtype=np.float32))
    audio = recorder.stop()

    # The recovered capture is whole, and says so for the utterance summary.
    assert audio.size == 800
    assert recorder.last_capture.recovered is True


def test_a_recovery_that_also_fails_to_activate_gives_up(caplog):
    error = FakePortAudioError("device unavailable")
    sounddevice = FakeSoundDevice(stream_start_error=error)
    recorder = _prepared(sounddevice)

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(FakePortAudioError):
        recorder.start()

    # Exactly one recovery attempt, and nothing retained afterwards.
    assert len(sounddevice.attempts) == 2
    assert len(sounddevice.streams) == 2
    assert [stream.closes for stream in sounddevice.streams] == [1, 1]
    assert recorder.state is RecorderState.UNPREPARED
    assert recorder._stream is None
    warnings = _warnings(caplog)
    assert "recorder: activation_failed" in warnings[0]
    assert "recorder: recovery_failed" in warnings[1]
    assert "phase=activate" in warnings[1]


def test_an_unprepared_recorder_gets_one_attempt_and_no_recovery(caplog):
    error = FakePortAudioError("device unavailable")
    sounddevice = FakeSoundDevice(stream_start_error=error)
    recorder = Recorder(device=1, max_seconds=5)
    # Prepared once and released, so the module is remembered but nothing is
    # retained: start() negotiates from scratch and gets no second chance.
    recorder.prepare(sounddevice)
    recorder.close()
    sounddevice.attempts.clear()

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(FakePortAudioError):
        recorder.start()

    assert len(sounddevice.attempts) == 1
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "recorder: activation_failed" in warnings[0]
    assert "retained=0" in warnings[0]


def test_a_later_prepare_reuses_the_module_the_recorder_was_built_on():
    sounddevice = FakeSoundDevice()
    recorder = Recorder(device=1, max_seconds=5)

    recorder.prepare(sounddevice)
    recorder.close()
    recorder.prepare()

    # No argument, and still no real PortAudio import: the retained module is
    # what the second negotiation used.
    assert recorder._sounddevice is sounddevice
    assert len(sounddevice.attempts) == 2
    assert len(sounddevice.streams) == 2
    assert recorder.is_prepared is True


def test_preparing_an_already_prepared_recorder_is_a_no_op():
    sounddevice = FakeSoundDevice()
    recorder = _prepared(sounddevice)

    recorder.prepare(sounddevice)

    assert len(sounddevice.attempts) == 1
