# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for capture configuration, the RMS gate, and resampling.

Constructing a ``Recorder`` is pure. Its stream lifecycle touches PortAudio and
is covered by the integration smoke suite, never by mocking (the testing policy
in AGENTS.md).
"""

from __future__ import annotations

import numpy as np
import pytest

from stenographer.audio import (
    Recorder,
    _resample_poly,
    speech_gate_passes,
    speech_gate_stats,
)

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
    assert speech_gate_passes(silence, _RATE, 0.0) is True


def test_gate_rejects_pure_silence():
    silence = np.zeros(_RATE, dtype=np.float32)
    assert speech_gate_passes(silence, _RATE, 0.0005) is False


def test_gate_rejects_isolated_loud_frame():
    # One loud frame surrounded by silence: no two consecutive loud frames.
    audio = _signal([0.0, 0.0, 0.02, 0.0, 0.0])
    assert speech_gate_passes(audio, _RATE, 0.0005) is False


def test_gate_passes_two_consecutive_loud_frames():
    audio = _signal([0.0, 0.02, 0.02, 0.0])
    assert speech_gate_passes(audio, _RATE, 0.0005) is True


def test_gate_passes_quiet_mic_speech():
    # RMS ~0.001 sustained speech clears the 0.0005 default the owner relies on.
    audio = _signal([0.001] * 10)
    assert speech_gate_passes(audio, _RATE, 0.0005) is True


def test_gate_rejects_speech_below_threshold():
    audio = _signal([0.001] * 10)
    assert speech_gate_passes(audio, _RATE, 0.01) is False


def test_gate_rejects_too_short_for_two_frames():
    # Fewer than two whole frames can never satisfy the consecutive rule.
    loud = np.full(_FRAME, 0.02, dtype=np.float32)
    assert speech_gate_passes(loud, _RATE, 0.0005) is False


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
    assert speech_gate_passes(silence, _RATE, min_rms) is True


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


def test_gate_stats_and_the_verdict_come_from_one_computation():
    # ``speech_gate_passes`` must not be able to disagree with the stats line
    # printed beside it. Seen to FAIL against a ``speech_gate_passes`` left as
    # its own second implementation with the two-frame minimum dropped.
    cases = [
        (_signal([0.0, 0.0]), 0.0005),
        (_signal([0.0, 0.02, 0.02, 0.0]), 0.0005),
        (_signal([0.0, 0.0, 0.02, 0.0, 0.0]), 0.0005),
        (np.full(_FRAME, 0.02, dtype=np.float32), 0.0005),
        (np.zeros(_RATE, dtype=np.float32), 0.0),
        (np.empty(0, dtype=np.float32), 0.0005),
    ]
    for audio, min_rms in cases:
        assert speech_gate_passes(audio, _RATE, min_rms) is (
            speech_gate_stats(audio, _RATE, min_rms).passed
        )


def test_gate_stats_on_audio_too_short_to_frame():
    stats = speech_gate_stats(np.empty(0, dtype=np.float32), _RATE, 0.0005)

    assert stats.frames_total == 0
    assert stats.frames_above == 0
    assert stats.peak_rms == 0.0
    assert stats.passed is False
