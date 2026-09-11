# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared, host-free contracts for ASR and cleanup experiments.

Adapters own deadlines and cancellation while working. The caller checks again
before accepting a result; a late result must never revive a cancelled utterance.
No process management, model downloads, or backend selection occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Failure(StrEnum):
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    CONTEXT = "context_exceeded"
    CRASH = "crash"
    UNCERTAIN = "uncertain_boundary"


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class Request:
    utterance: int
    deadline: float
    cancel: Cancellation = field(repr=False)

    def failure_at(self, now: float) -> Failure | None:
        if self.cancel.is_set():
            return Failure.CANCELLED
        return Failure.TIMEOUT if now >= self.deadline else None


@dataclass(frozen=True)
class Timings:
    load_ms: float | None = None
    inference_ms: float | None = None
    queue_ms: float | None = None


@dataclass(frozen=True)
class Result[T]:
    value: T | None = field(default=None, repr=False)
    failure: Failure | None = None
    timings: Timings = field(default_factory=Timings)

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("result requires exactly one value or failure")
