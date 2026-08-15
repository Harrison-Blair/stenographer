# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe lifecycle metadata shared by the daemon and overlay helper.

The display helper is optional and isolated from dictation.  This module keeps
its contract deliberately small: fixed enums, strict versioned NDJSON, and pure
generation/coalescing policy.  No protocol variant has a free-form payload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 512
MAX_GENERATION = (1 << 63) - 1
ERROR_DISPLAY_SECONDS = 2.5


class OverlayState(StrEnum):
    HIDDEN = "hidden"
    RECORDING = "recording"
    MODEL_LOADING = "model_loading"
    TRANSCRIBING = "transcribing"
    DELIVERING = "delivering"
    ERROR = "error"


class LifecycleEvent(StrEnum):
    """Metadata-only events which are not display states or labels."""

    MODEL_READY = "model_ready"


class Command(StrEnum):
    SHUTDOWN = "shutdown"


class Backend(StrEnum):
    LAYER_SHELL = "layer-shell"
    XWAYLAND = "xwayland"


class UnavailableReason(StrEnum):
    """Fixed diagnostics safe to expose to the parent and ``doctor``."""

    NO_WAYLAND_DISPLAY = "no_wayland_display"
    WAYLAND_CONNECT_FAILED = "wayland_connect_failed"
    REQUIRED_GLOBALS_MISSING = "required_wayland_globals_missing"
    NO_X_DISPLAY = "no_x_display"
    X_CONNECT_FAILED = "x_connect_failed"
    X_ARGB_UNAVAILABLE = "x_argb_unavailable"
    X_EXTENSIONS_UNAVAILABLE = "x_extensions_unavailable"
    BACKENDS_UNAVAILABLE = "backends_unavailable"
    BACKEND_LOST = "backend_lost"
    HELPER_CRASHED = "helper_crashed"
    PROTOCOL_ERROR = "protocol_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class StateMessage:
    generation: int
    state: OverlayState


@dataclass(frozen=True, slots=True)
class LifecycleMessage:
    generation: int
    event: LifecycleEvent


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
    StateMessage | LifecycleMessage | CommandMessage | ReadyMessage | UnavailableMessage
)


class ProtocolError(ValueError):
    """A malformed helper message, described without reproducing its payload."""


def _valid_generation(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_GENERATION


def _expect_fields(obj: dict, fields: frozenset[str]) -> None:
    if frozenset(obj) != fields:
        raise ProtocolError("protocol record has unexpected fields")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ProtocolError("protocol record has duplicate fields")
        obj[key] = value
    return obj


def _enum_value(enum_type, value: object, field: str):
    if not isinstance(value, str):
        raise ProtocolError(f"protocol field {field} has wrong type")
    try:
        return enum_type(value)
    except ValueError:
        raise ProtocolError(f"protocol field {field} has unknown value") from None


def encode_message(message: ProtocolMessage) -> str:
    """Encode exactly one bounded NDJSON record."""
    if isinstance(message, StateMessage):
        if not _valid_generation(message.generation):
            raise ProtocolError("protocol generation is out of range")
        if not isinstance(message.state, OverlayState):
            raise ProtocolError("protocol state has wrong type")
        payload = {
            "v": PROTOCOL_VERSION,
            "type": "state",
            "generation": message.generation,
            "state": message.state.value,
        }
    elif isinstance(message, LifecycleMessage):
        if not _valid_generation(message.generation):
            raise ProtocolError("protocol generation is out of range")
        if not isinstance(message.event, LifecycleEvent):
            raise ProtocolError("protocol lifecycle event has wrong type")
        payload = {
            "v": PROTOCOL_VERSION,
            "type": "lifecycle",
            "generation": message.generation,
            "event": message.event.value,
        }
    elif isinstance(message, CommandMessage):
        if not isinstance(message.command, Command):
            raise ProtocolError("protocol command has wrong type")
        payload = {"v": PROTOCOL_VERSION, "type": "command", "command": message.command.value}
    elif isinstance(message, ReadyMessage):
        if not isinstance(message.backend, Backend):
            raise ProtocolError("protocol backend has wrong type")
        payload = {"v": PROTOCOL_VERSION, "type": "ready", "backend": message.backend.value}
    elif isinstance(message, UnavailableMessage):
        if not isinstance(message.reason, UnavailableReason):
            raise ProtocolError("protocol unavailable reason has wrong type")
        payload = {"v": PROTOCOL_VERSION, "type": "unavailable", "reason": message.reason.value}
    else:
        raise ProtocolError("unsupported protocol message type")
    record = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    if len(record.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("protocol record is too large")
    return record


def decode_message(record: str | bytes) -> ProtocolMessage:
    """Decode one strict NDJSON record without reflecting malformed content."""
    if isinstance(record, bytes):
        if len(record) > MAX_MESSAGE_BYTES:
            raise ProtocolError("protocol record is too large")
        try:
            record = record.decode("utf-8")
        except UnicodeDecodeError:
            raise ProtocolError("protocol record is not UTF-8") from None
    elif not isinstance(record, str):
        raise ProtocolError("protocol record has wrong type")
    if len(record.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("protocol record is too large")
    if record.endswith("\n"):
        record = record[:-1]
    if not record or "\n" in record or "\r" in record:
        raise ProtocolError("protocol record is not one NDJSON line")
    try:
        obj = json.loads(record, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, RecursionError):
        raise ProtocolError("protocol record is not valid JSON") from None
    if not isinstance(obj, dict):
        raise ProtocolError("protocol record is not an object")
    version = obj.get("v")
    if not isinstance(version, int) or isinstance(version, bool) or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    message_type = obj.get("type")
    if message_type == "state":
        _expect_fields(obj, frozenset({"v", "type", "generation", "state"}))
        if not _valid_generation(obj["generation"]):
            raise ProtocolError("protocol generation is out of range")
        return StateMessage(obj["generation"], _enum_value(OverlayState, obj["state"], "state"))
    if message_type == "lifecycle":
        _expect_fields(obj, frozenset({"v", "type", "generation", "event"}))
        if not _valid_generation(obj["generation"]):
            raise ProtocolError("protocol generation is out of range")
        return LifecycleMessage(
            obj["generation"], _enum_value(LifecycleEvent, obj["event"], "event")
        )
    if message_type == "command":
        _expect_fields(obj, frozenset({"v", "type", "command"}))
        return CommandMessage(_enum_value(Command, obj["command"], "command"))
    if message_type == "ready":
        _expect_fields(obj, frozenset({"v", "type", "backend"}))
        return ReadyMessage(_enum_value(Backend, obj["backend"], "backend"))
    if message_type == "unavailable":
        _expect_fields(obj, frozenset({"v", "type", "reason"}))
        return UnavailableMessage(_enum_value(UnavailableReason, obj["reason"], "reason"))
    raise ProtocolError("protocol record has unknown message type")


@dataclass(slots=True)
class GenerationGate:
    """Accept strictly increasing generations. Deterministic and I/O-free."""

    current: int = -1

    def accept(self, candidate: int) -> bool:
        if not _valid_generation(candidate):
            raise ValueError("generation must be a non-negative signed 64-bit integer")
        if candidate <= self.current:
            return False
        self.current = candidate
        return True


def coalesce_latest_state(pending: StateMessage | None, candidate: StateMessage) -> StateMessage:
    """Keep only the newest pending state for a bounded writer slot."""
    if pending is None or candidate.generation > pending.generation:
        return candidate
    return pending


def error_timeout_applies(expected_generation: int, current: StateMessage) -> bool:
    """Guard a delayed hide so it cannot erase a newer visible state."""
    return current.generation == expected_generation and current.state is OverlayState.ERROR


@runtime_checkable
class StatusSink(Protocol):
    """Nonblocking daemon-side lifecycle destination.

    Concrete sinks may enqueue work, but these calls must not perform display or
    child-process I/O because hotkey callbacks invoke them under the daemon lock.
    """

    def publish(self, state: OverlayState) -> None: ...

    def lifecycle(self, event: LifecycleEvent) -> None: ...

    def close(self) -> None: ...


class NullStatusSink:
    """No-op sink used when the overlay is disabled or unavailable."""

    def publish(self, state: OverlayState) -> None:
        pass

    def lifecycle(self, event: LifecycleEvent) -> None:
        pass

    def close(self) -> None:
        pass
