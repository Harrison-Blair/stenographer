# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy-safe lifecycle and display data shared with the overlay helper.

The display helper is optional and isolated from dictation.  This module keeps
its contract deliberately small: fixed enums, strict versioned NDJSON, and pure
generation/coalescing policy.  The only model-load metadata is a boolean whose
pulse timing stays helper-local.  No protocol variant has a free-form payload
or contains raw microphone samples.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

PROTOCOL_VERSION = 4
MAX_MESSAGE_BYTES = 512
MAX_GENERATION = (1 << 63) - 1
ERROR_DISPLAY_SECONDS = 2.5
SPECTRUM_BANDS = 18


class OverlayState(StrEnum):
    HIDDEN = "hidden"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    DELIVERING = "delivering"
    ERROR = "error"


def should_publish_state(current: OverlayState, candidate: OverlayState) -> bool:
    """Return whether a daemon state update needs a new helper generation. PURE.

    Stable operational states are coalesced, but each error represents a new
    failure and therefore needs its own display deadline.
    """
    return candidate is OverlayState.ERROR or candidate is not current


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
    # A v4-compatible vocabulary extension: the reason set is fixed data, not a
    # framing change, so adding one value bumps no protocol version.
    BACKEND_DEPENDENCY_MISSING = "backend_dependency_missing"
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


class ProtocolError(ValueError):
    """A malformed helper message, described without reproducing its payload."""


def _valid_generation(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_GENERATION


def _valid_levels(value: object) -> bool:
    return (
        isinstance(value, tuple | list)
        and len(value) == SPECTRUM_BANDS
        and all(
            isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 255
            for level in value
        )
    )


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
    elif isinstance(message, SpectrumMessage):
        if not _valid_generation(message.generation):
            raise ProtocolError("protocol generation is out of range")
        if not _valid_generation(message.sequence):
            raise ProtocolError("protocol sequence is out of range")
        if not isinstance(message.levels, tuple) or not _valid_levels(message.levels):
            raise ProtocolError("protocol spectrum levels are invalid")
        payload = {
            "v": PROTOCOL_VERSION,
            "type": "spectrum",
            "generation": message.generation,
            "sequence": message.sequence,
            "levels": list(message.levels),
        }
    elif isinstance(message, LoadingActivityMessage):
        if not isinstance(message.active, bool):
            raise ProtocolError("protocol loading activity has wrong type")
        payload = {
            "v": PROTOCOL_VERSION,
            "type": "loading_activity",
            "active": message.active,
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
    if message_type == "spectrum":
        _expect_fields(obj, frozenset({"v", "type", "generation", "sequence", "levels"}))
        if not _valid_generation(obj["generation"]):
            raise ProtocolError("protocol generation is out of range")
        if not _valid_generation(obj["sequence"]):
            raise ProtocolError("protocol sequence is out of range")
        if not _valid_levels(obj["levels"]):
            raise ProtocolError("protocol spectrum levels are invalid")
        return SpectrumMessage(obj["generation"], obj["sequence"], tuple(obj["levels"]))
    if message_type == "loading_activity":
        _expect_fields(obj, frozenset({"v", "type", "active"}))
        if not isinstance(obj["active"], bool):
            raise ProtocolError("protocol loading activity has wrong type")
        return LoadingActivityMessage(obj["active"])
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


class LineReader:
    """Bounded incremental NDJSON framing shared by pipe and display loops."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._buffer.extend(chunk)
        records = []
        while (newline := self._buffer.find(b"\n")) >= 0:
            record = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            if len(record) > MAX_MESSAGE_BYTES:
                raise ProtocolError("protocol record is too large")
            records.append(record)
        if len(self._buffer) >= MAX_MESSAGE_BYTES:
            raise ProtocolError("protocol record is too large")
        return records

    def finish(self) -> None:
        if self._buffer:
            raise ProtocolError("protocol stream ended mid-record")


@dataclass(slots=True)
class DisplayMessageGate:
    """Reject stale generated records without coupling loading to recording. PURE."""

    current: int = -1
    recording_generation: int | None = None
    sequence: int = -1
    loading_active: bool = False

    def accept(
        self,
        message: StateMessage | SpectrumMessage | LoadingActivityMessage,
    ) -> bool:
        if isinstance(message, LoadingActivityMessage):
            self.loading_active = message.active
            return True
        if isinstance(message, SpectrumMessage):
            if message.generation != self.recording_generation or message.sequence <= self.sequence:
                return False
            self.sequence = message.sequence
            return True
        if not isinstance(message, StateMessage):
            raise TypeError("display gate accepts only generated display messages")
        if not _valid_generation(message.generation):
            raise ValueError("generation must be a non-negative signed 64-bit integer")
        if message.generation <= self.current:
            return False
        self.current = message.generation
        self.recording_generation = (
            message.generation if message.state is OverlayState.RECORDING else None
        )
        self.sequence = -1
        return True


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


@runtime_checkable
class StatusSink(Protocol):
    """Nonblocking daemon-side lifecycle destination.

    Concrete sinks may enqueue work, but these calls must not perform display or
    child-process I/O because hotkey callbacks invoke them under the daemon lock.
    """

    def publish(self, state: OverlayState) -> None: ...

    def loading_activity(self, active: bool) -> None: ...

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None: ...

    def close(self) -> None: ...


class NullStatusSink:
    """No-op sink used when the overlay is disabled or unavailable."""

    def publish(self, state: OverlayState) -> None:
        pass

    def loading_activity(self, active: bool) -> None:
        pass

    def audio_block(self, samples: object, sample_rate: int, stream_epoch: int) -> None:
        pass

    def close(self) -> None:
        pass
