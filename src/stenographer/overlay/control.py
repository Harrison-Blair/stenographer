# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure helper-to-supervisor handshake policy, independent of framing and transport."""

from dataclasses import dataclass
from typing import Literal

from stenographer.status import ProtocolError, ProtocolMessage, ReadyMessage, UnavailableMessage


@dataclass(frozen=True)
class HelperControlState:
    ready: bool = False
    unavailable: bool = False
    lost: bool = False

    @property
    def expected_exit(self) -> bool:
        return self.unavailable


@dataclass(frozen=True)
class HelperControlTransition:
    state: HelperControlState
    event: Literal["ready", "unavailable", "backend_lost"]
    value: str
    stop: bool = False


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
