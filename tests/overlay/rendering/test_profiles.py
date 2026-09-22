# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile metadata stays attached to every visible lifecycle stage."""

from __future__ import annotations

import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.messages import StateMessage
from stenographer.overlay.rendering.constants import (
    _DOT_DIAMETER,
    _DOT_RIGHT_INSET,
    _PROFILE_LABEL_EXTRA,
)
from stenographer.overlay.rendering.reducer import OverlayReducer
from stenographer.overlay.rendering.render import render_overlay, spectrum_bar_bounds


def test_profile_round_trips_with_a_state_message():
    message = StateMessage(4, OverlayState.REFINING, RefineProfile.AGENT)
    assert decode_message(encode_message(message)) == message


def test_reducer_keeps_profile_for_rendering():
    reducer = OverlayReducer()
    reducer.apply(StateMessage(1, OverlayState.RECORDING, RefineProfile.GENERAL), 1.0)
    assert reducer.profile is RefineProfile.GENERAL
    assert render_overlay(
        OverlayState.RECORDING,
        levels=(0,) * 18,
        profile=reducer.profile,
    ).image.getbbox()


@pytest.mark.parametrize("profile", list(RefineProfile))
def test_profiled_recording_keeps_the_spectrum_inside_the_pill(profile: RefineProfile) -> None:
    """The profile label must not push the bar rail past the pill or onto the dot."""
    levels = (255,) * SPECTRUM_BANDS
    frame = render_overlay(OverlayState.RECORDING, levels=levels, profile=profile)
    left, top, right, bottom = frame.pill_bounds

    bars = spectrum_bar_bounds(
        levels,
        pill_bounds=frame.pill_bounds,
        left_offset=_PROFILE_LABEL_EXTRA,
    )
    dot_left_edge = right - _DOT_RIGHT_INSET - _DOT_DIAMETER // 2

    assert bars[0][0] > left
    assert bars[-1][2] <= dot_left_edge
    assert min(bar[1] for bar in bars) >= top
    assert max(bar[3] for bar in bars) <= bottom


def test_refine_outcomes_are_transient_states():
    from stenographer.overlay.protocol.ordering import transient_display_seconds

    assert all(
        transient_display_seconds(state) is not None
        for state in (OverlayState.APPLIED, OverlayState.SKIPPED, OverlayState.FALLBACK)
    )
