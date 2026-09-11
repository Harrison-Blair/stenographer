# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import NamedTuple

import numpy as np


class _BandAnalysis(NamedTuple):
    """Per-stream analysis constants shared across every frame of a stream."""

    window: np.ndarray
    coherent_gain: float
    fft_size: int
    bands: tuple[tuple[int, int] | None, ...]
