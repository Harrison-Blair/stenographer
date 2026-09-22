# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile metadata stays attached to every visible lifecycle stage."""

from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.messages import StateMessage
from stenographer.overlay.rendering.reducer import OverlayReducer
from stenographer.overlay.rendering.render import render_overlay


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


def test_refine_outcomes_are_transient_states():
    from stenographer.overlay.protocol.ordering import transient_display_seconds

    assert all(
        transient_display_seconds(state) is not None
        for state in (OverlayState.APPLIED, OverlayState.SKIPPED, OverlayState.FALLBACK)
    )
