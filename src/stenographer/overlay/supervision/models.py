# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RestartBudget:
    """Pure one-way retry budget for unexpected helper exits."""

    remaining: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.remaining, bool) or self.remaining < 0:
            raise ValueError("restart budget must be a non-negative integer")

    def on_exit(self, *, unexpected: bool) -> bool:
        if not unexpected or self.remaining == 0:
            return False
        self.remaining -= 1
        return True


@dataclass(frozen=True, slots=True)
class _AudioBlock:
    """One copied block tagged with daemon-only recording and stream identities."""

    generation: int
    samples: object
    sample_rate: int
    stream_epoch: int


@dataclass(frozen=True, slots=True)
class _ProcessOutcome:
    expected: bool
    unavailable: bool = False
