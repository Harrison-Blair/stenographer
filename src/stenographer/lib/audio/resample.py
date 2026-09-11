# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable NumPy polyphase resampling."""

from __future__ import annotations

import math

import numpy as np


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
    if up == 1 and down == 1:
        return data
    n_taps = 2 * 10 * max(up, down) + 1
    half = n_taps // 2
    cutoff = 1.0 / max(up, down)
    n = np.arange(n_taps, dtype=np.float64) - half
    filt = np.sinc(cutoff * n) * cutoff * np.hanning(n_taps)
    filt = (filt * up).astype(np.float32)
    # Output m taps the virtual full convolution at n = half + m*down; grouping
    # by p = n % up turns each group into a plain convolution with sub-filter
    # filt[p::up], sampled at q = n // up, so no zero-stuffed array is built.
    total = data.size * up + n_taps - 1
    ms = np.arange((total - half + down - 1) // down)
    ns = half + ms * down
    ps = ns % up
    qs = ns // up
    out = np.zeros(ms.size, dtype=np.float32)
    for p in np.unique(ps):
        sel = ps == p
        conv_p = np.convolve(data, filt[p::up], mode="full")
        q_sel = qs[sel]
        valid = q_sel < conv_p.size
        vals = np.zeros(q_sel.size, dtype=np.float32)
        vals[valid] = conv_p[q_sel[valid]]
        out[sel] = vals
    return out
