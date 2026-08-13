# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the capture module: the RMS gate and the resampler.

``Recorder`` itself touches PortAudio and is covered by the integration smoke
suite, never by mocking (§6).
"""

from __future__ import annotations

import numpy as np
import pytest
from stenographer_v2.audio import _resample_poly, speech_gate_passes

_RATE = 16000
_FRAME = int(_RATE * 0.050)  # 800 samples per 50 ms gate frame


def _signal(frame_amplitudes: list[float]) -> np.ndarray:
    """Build audio whose i-th 50 ms frame is a constant at the given amplitude."""
    return np.concatenate([np.full(_FRAME, amp, dtype=np.float32) for amp in frame_amplitudes])


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
