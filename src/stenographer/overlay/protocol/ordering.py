# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Iterable, Sequence

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.codec import decode_message
from stenographer.overlay.protocol.display_message_gate import DisplayMessageGate
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.line_reader import LineReader
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


def selected_unavailable_reason(
    reasons: Sequence[UnavailableReason | None],
) -> UnavailableReason:
    """Pick the reason to report once every overlay backend has refused. PURE.

    The last *specific* reason wins: backends are tried in preference order, so
    the last one to refuse is the final fallback, and its complaint is the one
    that describes what the session actually lacks. ``BACKENDS_UNAVAILABLE``
    survives only for the genuinely unknown case — no backend offered a reason,
    or none was registered at all.

    It lives here, with the vocabulary, because two callers must agree: the
    helper folding its construct failures (``overlay/helper/execution.py``) and the
    read-only probe behind ``doctor`` (``capabilities.probe_overlay``). A
    second copy of the policy would let the report and the log disagree about
    the same session.
    """
    specific = [
        reason
        for reason in reasons
        if reason is not None and reason is not UnavailableReason.BACKENDS_UNAVAILABLE
    ]
    return specific[-1] if specific else UnavailableReason.BACKENDS_UNAVAILABLE


def coalesce_spectrum_messages(
    messages: Iterable[StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage],
) -> tuple[
    StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage,
    ...,
]:
    """Replace adjacent spectrum frames while retaining every ordering barrier."""
    pending: list[StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage] = []
    for message in messages:
        if (
            isinstance(message, SpectrumMessage)
            and pending
            and isinstance(pending[-1], SpectrumMessage)
        ):
            pending[-1] = message
        else:
            pending.append(message)
    return tuple(pending)


def drain_display_stream(
    chunk: bytes,
    reader: LineReader,
    gate: DisplayMessageGate,
) -> tuple[StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage, ...]:
    """Frame, decode, gate, and coalesce one chunk of the parent display stream.

    Only display and command records are valid from the parent; any other
    protocol message raises ``ProtocolError`` without reflecting its content.
    """
    accepted: list[StateMessage | SpectrumMessage | LoadingActivityMessage | CommandMessage] = []
    for record in reader.feed(chunk):
        message = decode_message(record)
        if isinstance(message, StateMessage | SpectrumMessage | LoadingActivityMessage):
            if not gate.accept(message):
                continue
        elif not isinstance(message, CommandMessage):
            raise ProtocolError("unexpected parent protocol message")
        accepted.append(message)
    return coalesce_spectrum_messages(accepted)


def error_timeout_applies(expected_generation: int, current: StateMessage) -> bool:
    """Guard a delayed hide so it cannot erase a newer visible state."""
    return current.generation == expected_generation and current.state is OverlayState.ERROR
