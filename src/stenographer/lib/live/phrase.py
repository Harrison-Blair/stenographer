# SPDX-License-Identifier: GPL-3.0-or-later
"""A speech phrase cut from one live audio source."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Phrase:
    """One VAD speech interval with times in the session clock."""

    source: str
    start: float
    end: float
    samples: np.ndarray
