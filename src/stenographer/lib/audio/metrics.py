# SPDX-License-Identifier: GPL-3.0-or-later
"""Scalar capture-clock bookkeeping; supplied timestamps, no host calls or audio."""

from __future__ import annotations

from collections.abc import Iterable

from stenographer.lib.audio.callback_clock import CallbackClock


def reduce_clock(
    metadata: Iterable[tuple[float, float, int]],
    *,
    rate: int,
    first_callback_at: float | None,
) -> CallbackClock:
    """Reduce a contiguous retained metadata suffix; omission is not an ADC gap."""
    clock = CallbackClock()
    for callback_at, adc_at, frames in metadata:
        clock.observe(callback_at=callback_at, adc_at=adc_at, frames=frames, rate=rate)
    clock.first_callback_at = first_callback_at
    return clock


def elapsed_ms(origin: float, timestamp: float | None) -> float | None:
    """Unknown stays unknown; clocks must share an origin."""
    return None if timestamp is None else (timestamp - origin) * 1000
