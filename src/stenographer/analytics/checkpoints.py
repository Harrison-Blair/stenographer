# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable cumulative measurements and the deliberately shared resource window."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from stenographer.analytics.metrics import OUTCOMES, PHASES, clean_context, clean_metrics
from stenographer.analytics.resources import ResourceSummary


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


def advance_checkpoint(
    old: Checkpoint,
    phase: str,
    *,
    updated_at: str,
    monotonic_now: float,
    metrics: Mapping[str, object] | None = None,
    context: Mapping[str, object] | None = None,
    outcome: str | None = None,
) -> Checkpoint:
    """Advance revision and phase while retaining cumulative measurements. PURE."""
    if phase not in PHASES:
        raise ValueError("Unknown analytics checkpoint phase")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError("Invalid analytics outcome")
    if PHASES.index(phase) < PHASES.index(old.phase):
        raise ValueError("Checkpoint phase cannot regress")
    return replace(
        old,
        updated_at=updated_at,
        revision=old.revision + 1,
        phase=phase,
        outcome=outcome or old.outcome,
        metrics={**old.metrics, **clean_metrics(metrics or {})},
        context={**old.context, **clean_context(context or {})},
        monotonic_finished=monotonic_now if phase == "terminal" else old.monotonic_finished,
    )
