# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@dataclass(frozen=True, slots=True)
class StateMessage:
    generation: int
    state: OverlayState


@dataclass(frozen=True, slots=True)
class SpectrumMessage:
    generation: int
    sequence: int
    levels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LoadingActivityMessage:
    active: bool


@dataclass(frozen=True, slots=True)
class CommandMessage:
    command: Command


@dataclass(frozen=True, slots=True)
class ReadyMessage:
    backend: Backend


@dataclass(frozen=True, slots=True)
class UnavailableMessage:
    reason: UnavailableReason


ProtocolMessage = (
    StateMessage
    | SpectrumMessage
    | LoadingActivityMessage
    | CommandMessage
    | ReadyMessage
    | UnavailableMessage
)
