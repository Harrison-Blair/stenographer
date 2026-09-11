# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured model-loading and inference phase durations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerTimings:
    """How one ``transcribe`` call spent its wall clock, in milliseconds.

    ``decode_ms`` is measured inside the child around inference; ``round_trip_ms``
    includes request/response transport. Failed phases retain elapsed boundaries
    while unobserved inference remains unknown. ``load_ms`` is absent on a warm
    model; concurrent press-lazy warm-up is measured separately by the daemon.
    """

    lock_wait_ms: float
    load_ms: float | None
    decode_ms: float | None
    round_trip_ms: float | None = None
