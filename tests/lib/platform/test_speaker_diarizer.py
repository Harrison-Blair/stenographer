# SPDX-License-Identifier: GPL-3.0-or-later
"""Finality of live speaker segments."""

from __future__ import annotations

import math

from stenographer.lib.platform.speaker_diarizer import (
    FINAL_LAG_SECONDS,
    SpeakerSegment,
    finalize_all,
    split_final,
)

A = SpeakerSegment(0, 0.0, 2.0)
B = SpeakerSegment(1, 2.5, 4.0)
OPEN = SpeakerSegment(0, 4.5, 5.0)


def test_segments_ending_before_the_lag_are_final_and_the_rest_is_tail() -> None:
    edge = 4.0 + FINAL_LAG_SECONDS

    final, tail, until = split_final([A, B, OPEN], edge, -math.inf)

    assert final == (A, B)
    assert tail == (OPEN,)
    assert until == 4.0


def test_a_segment_at_the_live_edge_is_not_final() -> None:
    final, tail, _ = split_final([A], 2.0 + FINAL_LAG_SECONDS - 0.01, -math.inf)

    assert final == ()
    assert tail == (A,)


def test_each_final_segment_is_returned_once_as_the_edge_moves() -> None:
    until = -math.inf
    seen = []
    for edge in (1.0, 3.0, 4.5, 5.0, 6.0, 9.0):
        final, _, until = split_final([A, B, OPEN], edge, until)
        seen.extend(final)

    assert seen == [A, B, OPEN]


def test_tail_segment_that_grows_becomes_final_with_its_new_end() -> None:
    until = -math.inf
    _, tail, until = split_final([SpeakerSegment(0, 0.0, 1.0)], 1.2, until)
    grown = SpeakerSegment(0, 0.0, 3.0)

    final, tail, until = split_final([grown], 3.0 + FINAL_LAG_SECONDS, until)

    assert final == (grown,)
    assert tail == ()


def test_finish_returns_every_segment_not_yet_final() -> None:
    _, _, until = split_final([A, B, OPEN], 4.0 + FINAL_LAG_SECONDS, -math.inf)

    assert finalize_all([A, B, OPEN], until) == (OPEN,)
    assert finalize_all([A, B, OPEN], -math.inf) == (A, B, OPEN)
