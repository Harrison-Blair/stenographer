# SPDX-License-Identifier: GPL-3.0-or-later
from stenographer.overlay.helper.models import HelperControlState, HelperControlTransition
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import ProtocolMessage, ReadyMessage, UnavailableMessage


def reduce_helper_control(
    state: HelperControlState, message: ProtocolMessage
) -> HelperControlTransition:
    """Validate order and return a fixed diagnostic plus an optional stop intent."""
    if isinstance(message, ReadyMessage) and not (state.ready or state.unavailable or state.lost):
        return HelperControlTransition(
            HelperControlState(ready=True), "ready", message.backend.value
        )
    if isinstance(message, UnavailableMessage):
        if state.unavailable or state.lost:
            raise ProtocolError("duplicate helper terminal message")
        if state.ready:
            return HelperControlTransition(
                HelperControlState(ready=True, lost=True),
                "backend_lost",
                message.reason.value,
                True,
            )
        return HelperControlTransition(
            HelperControlState(unavailable=True), "unavailable", message.reason.value
        )
    raise ProtocolError("unexpected helper protocol message")
