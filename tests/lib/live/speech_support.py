# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for the pyannote pass: each steady level of the samples is one piece of speech."""

from __future__ import annotations

import numpy as np

RATE = 16000
_STEP = RATE // 20
_SILENCE = 0.001
_SAME_LEVEL = 0.02


def level_pieces(samples, _speaker_model, *, progress, should_cancel):
    """Return the pieces of 0.5 s or more, as the real pass does. Silence gives no piece."""
    if should_cancel():
        return None
    runs = []
    for first in range(0, samples.size, _STEP):
        level = float(np.median(samples[first : first + _STEP]))
        end = min(first + _STEP, samples.size) / RATE
        if abs(level) < _SILENCE:
            continue
        if runs and runs[-1][1] == first / RATE and abs(runs[-1][2] - level) < _SAME_LEVEL:
            runs[-1][1] = end
        else:
            runs.append([first / RATE, end, level])
    progress(1.0)
    return tuple((start, end) for start, end, _ in runs if end - start >= 0.5)
