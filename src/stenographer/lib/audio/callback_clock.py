# SPDX-License-Identifier: GPL-3.0-or-later
"""Scalar ADC continuity measurements for one stream activation."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class CallbackClock:
    """One stream activation's ADC continuity, folded without retaining blocks.

    PortAudio clocks and perf_counter have different origins. Only differences
    within a clock are meaningful. Zero/nonfinite ADC timestamps mean unavailable.
    A discontinuity can be a driver clock reset; it is never labelled lost speech.
    """

    expected_adc_at: float | None = None
    max_adc_gap_ms: float | None = None
    adc_discontinuities: int = 0
    timing_count: int = 0

    def observe(self, *, adc_at: float, frames: int, rate: int) -> None:
        if not math.isfinite(adc_at) or adc_at <= 0 or rate <= 0 or frames <= 0:
            self.expected_adc_at = None
            return
        self.timing_count += 1
        if self.expected_adc_at is not None:
            gap = abs(adc_at - self.expected_adc_at)
            self.max_adc_gap_ms = max(self.max_adc_gap_ms or 0.0, gap * 1000)
            if gap > 1.5 / rate:
                self.adc_discontinuities += 1
        self.expected_adc_at = adc_at + frames / rate

    @classmethod
    def reduce_clock(
        cls, metadata: Iterable[tuple[float, float, int]], *, rate: int
    ) -> CallbackClock:
        """Reduce a contiguous retained metadata suffix; omission is not an ADC gap."""
        clock = cls()
        for _callback_at, adc_at, frames in metadata:
            clock.observe(adc_at=adc_at, frames=frames, rate=rate)
        return clock
