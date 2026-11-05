# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable NumPy polyphase resampling."""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def _polyphase_filter(up: int, down: int) -> np.ndarray:
    """The Hanning-windowed sinc shared by the batch and streaming resamplers."""
    n_taps = 2 * 10 * max(up, down) + 1
    cutoff = 1.0 / max(up, down)
    n = np.arange(n_taps, dtype=np.float64) - n_taps // 2
    return (np.sinc(cutoff * n) * cutoff * np.hanning(n_taps) * up).astype(np.float32)


def _resample_poly(data: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Polyphase FIR resample of mono float32 audio at rational rates.

    Cuts at ``min(rate_in, rate_out) / 2`` so it doubles as an anti-aliasing
    filter on downsample. Numpy-only. Returns ``data`` unchanged (as float32)
    when the rates match.
    """
    data = np.asarray(data, dtype=np.float32).reshape(-1)
    if rate_in == rate_out or data.size == 0:
        return data
    gcd = math.gcd(rate_in, rate_out)
    up = rate_out // gcd
    down = rate_in // gcd
    filt = _polyphase_filter(up, down)
    half = filt.size // 2
    longest_taps = (filt.size + up - 1) // up
    padded = np.concatenate(
        (np.zeros(longest_taps - 1, np.float32), data, np.zeros(longest_taps, np.float32))
    )
    # Output m taps the virtual full convolution at n = half + m*down. Outputs
    # up apart share the sub-filter filt[n % up::up] and read input windows
    # down apart, so each phase is one matrix product over a strided view.
    out = np.zeros((data.size * up + filt.size - 1 - half + down - 1) // down, dtype=np.float32)
    for phase in range(min(up, out.size)):
        n = half + phase * down
        taps = filt[n % up :: up]
        first_window = n // up + longest_taps - taps.size
        windows = sliding_window_view(padded, taps.size)[first_window::down]
        targets = out[phase::up]
        count = min(targets.size, windows.shape[0])
        targets[:count] = windows[:count] @ taps[::-1]
    return out
