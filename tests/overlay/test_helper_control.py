# SPDX-License-Identifier: GPL-3.0-or-later
"""Helper control ordering without a display or process."""

import pytest

from stenographer.overlay.control import HelperControlState, reduce_helper_control
from stenographer.status import (
    Backend,
    OverlayState,
    ProtocolError,
    ReadyMessage,
    StateMessage,
    UnavailableMessage,
    UnavailableReason,
)


def test_helper_ready_then_backend_loss_remains_unexpected():
    ready = ReadyMessage(Backend.LAYER_SHELL)
    transition = reduce_helper_control(HelperControlState(), ready)
    assert transition.state.ready and transition.event == "ready" and not transition.stop
    assert not transition.state.expected_exit
    with pytest.raises(ProtocolError):
        reduce_helper_control(transition.state, ready)
    lost = reduce_helper_control(
        transition.state, UnavailableMessage(UnavailableReason.BACKEND_DEPENDENCY_MISSING)
    )
    assert lost.event == "backend_lost" and lost.stop
    assert lost.value == "backend_dependency_missing" and not lost.state.expected_exit


def test_helper_refusal_preserves_specific_reason_and_rejects_later_controls():
    refusal = UnavailableMessage(UnavailableReason.BACKEND_DEPENDENCY_MISSING)
    transition = reduce_helper_control(HelperControlState(), refusal)
    assert transition.event == "unavailable" and transition.state.expected_exit
    assert transition.value == "backend_dependency_missing" and not transition.state.ready
    for message in (
        refusal,
        ReadyMessage(Backend.LAYER_SHELL),
        StateMessage(0, OverlayState.HIDDEN),
    ):
        with pytest.raises(ProtocolError):
            reduce_helper_control(transition.state, message)
    with pytest.raises(ProtocolError):
        reduce_helper_control(HelperControlState(), StateMessage(0, OverlayState.HIDDEN))
