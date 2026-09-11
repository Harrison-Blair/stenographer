# SPDX-License-Identifier: GPL-3.0-or-later
"""Clock diagnostics are independent from retained audio and metadata loss."""

from stenographer.lib.audio.metrics import reduce_clock


def test_retained_suffix_does_not_invent_gaps_or_lose_first_callback():
    clock = reduce_clock([(10, 50, 160), (10.01, 50.01, 160)], rate=16000, first_callback_at=1)
    assert clock.first_callback_at == 1
    assert clock.timing_count == 2
    assert clock.adc_discontinuities == 0
    assert clock.max_adc_gap_ms == 0


def test_missing_clock_breaks_comparison_and_real_discontinuity_is_counted():
    clock = reduce_clock(
        [(1, 5, 160), (2, 0, 160), (3, 7, 160), (4, 8, 160)], rate=16000, first_callback_at=1
    )
    assert clock.timing_count == 3
    assert clock.adc_discontinuities == 1
    assert abs(clock.max_adc_gap_ms - 990) < 1e-6
