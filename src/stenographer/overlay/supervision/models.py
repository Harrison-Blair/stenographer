# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _AudioBlock:
    """One copied block tagged with daemon-only recording and stream identities."""

    generation: int
    samples: object
    sample_rate: int
    stream_epoch: int
