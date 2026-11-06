# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire format still carries a profile; the overlay does not show one."""

from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.messages import StateMessage


def test_profile_round_trips_with_a_state_message():
    message = StateMessage(4, OverlayState.REFINING, RefineProfile.AGENT)
    assert decode_message(encode_message(message).encode()) == message


def test_refine_outcomes_are_transient_states():
    from stenographer.overlay.protocol.ordering import transient_display_seconds

    assert all(
        transient_display_seconds(state) is not None
        for state in (OverlayState.APPLIED, OverlayState.SKIPPED, OverlayState.FALLBACK)
    )
