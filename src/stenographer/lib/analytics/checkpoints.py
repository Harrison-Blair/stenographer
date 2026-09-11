# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable cumulative measurements and the deliberately shared resource window."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from stenographer.lib.analytics.checkpoint_records import Checkpoint
from stenographer.lib.analytics.metrics import OUTCOMES, PHASES, clean_context, clean_metrics


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
