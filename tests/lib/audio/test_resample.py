# SPDX-License-Identifier: GPL-3.0-or-later
"""The polyphase resampler and its streaming form (file decoding)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stenographer.lib.audio.resample import _polyphase_filter, _resample_poly
from stenographer.lib.audio.streaming_resampler import StreamingResampler

_RATE = 16000


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


def _zero_stuffed_reference(data: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """The textbook definition: stuff zeros, filter at the high rate, decimate."""
    gcd = math.gcd(rate_in, rate_out)
    up, down = rate_out // gcd, rate_in // gcd
    filt = _polyphase_filter(up, down)
    stuffed = np.zeros(data.size * up, dtype=np.float64)
    stuffed[::up] = data
    return np.convolve(stuffed, filt.astype(np.float64))[filt.size // 2 :: down]


@pytest.mark.parametrize("rate", [48000, 44100, 22050, 8000])
@pytest.mark.parametrize("frames", [1, 7, 500, 3000])
def test_resample_matches_the_zero_stuffed_definition(rate, frames):
    data = np.random.default_rng(frames).standard_normal(frames).astype(np.float32)

    out = _resample_poly(data, rate, 16000)

    expected = _zero_stuffed_reference(data, rate, 16000)
    assert out.size == expected.size
    assert out == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize("rate", [48000, 44100, 22050, 8000])
@pytest.mark.parametrize("block", [1, 37, 512, 20000])
def test_streaming_resampler_matches_the_definition_for_any_block_size(rate, block):
    data = np.random.default_rng(block).standard_normal(6000).astype(np.float32)
    resampler = StreamingResampler(rate, 16000)

    pieces = [resampler.process(data[i : i + block]) for i in range(0, data.size, block)]
    pieces.append(resampler.flush())
    out = np.concatenate(pieces)

    gcd = math.gcd(rate, 16000)
    assert out.size == math.ceil(data.size * (16000 // gcd) / (rate // gcd))
    assert out.dtype == np.float32
    assert out == pytest.approx(_zero_stuffed_reference(data, rate, 16000)[: out.size], abs=1e-5)


def test_streaming_resampler_emits_only_outputs_with_complete_input():
    resampler = StreamingResampler(48000, 16000)

    # A 3:1 filter has 61 taps, so output m centres on input 30 + 3m.
    assert resampler.process(np.ones(30, dtype=np.float32)).size == 0
    assert resampler.process(np.ones(1, dtype=np.float32)).size == 1
    assert resampler.process(np.ones(3, dtype=np.float32)).size == 1
