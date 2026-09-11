# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.constants import (
    MAX_GENERATION,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
)
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    ProtocolMessage,
    ReadyMessage,
    SpectrumMessage,
    StateMessage,
    UnavailableMessage,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


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
