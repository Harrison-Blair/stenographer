# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable cumulative analytics checkpoints and queued resource samples."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from stenographer.lib.analytics.metrics import clean_context, clean_metrics
from stenographer.lib.analytics.resources import ResourceSummary


@dataclass(frozen=True)
class Checkpoint:
    id: str
    run_id: str
    source: str
    started_at: str
    updated_at: str
    monotonic_started: float
    revision: int = 0
    phase: str = "accepted_start"
    outcome: str | None = None
    metrics: Mapping[str, int | float | bool] = field(default_factory=dict)
    context: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    monotonic_finished: float | None = None

    def __post_init__(self) -> None:
        # Copy before freezing: callers cannot mutate a queued snapshot through
        # the original dictionaries. All admitted values are immutable scalars.
        object.__setattr__(self, "metrics", MappingProxyType(clean_metrics(self.metrics)))
        object.__setattr__(self, "context", MappingProxyType(clean_context(self.context)))

    def to_store(self) -> dict[str, Any]:
        """Convert only at the persistence boundary; the schema stays unchanged."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "source": self.source,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "phase": self.phase,
            "outcome": self.outcome,
            "metrics": dict(self.metrics),
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class QueuedCheckpoint:
    checkpoint: Checkpoint
    resource: ResourceSummary | None = None
