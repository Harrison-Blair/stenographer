# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for lifecycle metadata and the versioned overlay protocol."""

from __future__ import annotations

import pytest

from stenographer.status import (
    MAX_MESSAGE_BYTES,
    Backend,
    Command,
    CommandMessage,
    GenerationGate,
    LifecycleEvent,
    LifecycleMessage,
    NullStatusSink,
    OverlayState,
    ProtocolError,
    ReadyMessage,
    StateMessage,
    UnavailableMessage,
    UnavailableReason,
    coalesce_latest_state,
    decode_message,
    encode_message,
    error_timeout_applies,
)


@pytest.mark.parametrize(
    "message",
    [
        StateMessage(generation=7, state=OverlayState.RECORDING),
        LifecycleMessage(generation=8, event=LifecycleEvent.MODEL_READY),
        CommandMessage(command=Command.SHUTDOWN),
        ReadyMessage(backend=Backend.LAYER_SHELL),
        ReadyMessage(backend=Backend.XWAYLAND),
        UnavailableMessage(reason=UnavailableReason.BACKENDS_UNAVAILABLE),
    ],
)
def test_protocol_round_trip_is_one_ndjson_record(message):
    encoded = encode_message(message)
    assert encoded.endswith("\n")
    assert encoded.count("\n") == 1
    assert len(encoded.encode()) <= MAX_MESSAGE_BYTES
    assert decode_message(encoded) == message


def test_protocol_uses_only_fixed_metadata_fields():
    encoded = encode_message(StateMessage(3, OverlayState.TRANSCRIBING))
    assert encoded == '{"v":1,"type":"state","generation":3,"state":"transcribing"}\n'
    assert "transcript" not in encoded
    assert "audio" not in encoded


@pytest.mark.parametrize(
    "record",
    [
        "",
        "not json\n",
        '{"v":2,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":1.0,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":1,"v":1,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":1,"type":"state","generation":0,"state":"hidden","state":"secret"}\n',
        '{"v":1,"type":"state","generation":true,"state":"hidden"}\n',
        '{"v":1,"type":"state","generation":-1,"state":"hidden"}\n',
        '{"v":1,"type":"state","generation":0,"state":"success"}\n',
        '{"v":1,"type":"state","generation":0,"state":"hidden","text":"secret"}\n',
        '{"v":1,"type":"lifecycle","generation":1,"event":"transcript_ready"}\n',
        '{"v":1,"type":"ready","backend":"gtk"}\n',
        '{"v":1,"type":"unavailable","reason":"a detailed display error"}\n',
        '{"v":1,"type":"command","command":"show_preview"}\n',
        '{"v":1,"type":"command","command":"shutdown"}\ntrailing',
    ],
)
def test_protocol_rejects_malformed_or_expansive_records_without_echo(record):
    with pytest.raises(ProtocolError) as exc:
        decode_message(record)
    assert "secret" not in str(exc.value)
    assert "detailed" not in str(exc.value)


def test_protocol_rejects_oversize_records_before_parsing():
    with pytest.raises(ProtocolError, match="too large"):
        decode_message(" " * (MAX_MESSAGE_BYTES + 1))


def test_encoder_rejects_invalid_typed_values():
    with pytest.raises(ProtocolError, match="state"):
        encode_message(StateMessage(1, "recording"))
    with pytest.raises(ProtocolError, match="generation"):
        encode_message(StateMessage(True, OverlayState.RECORDING))


def test_generation_gate_accepts_only_strictly_newer_messages():
    gate = GenerationGate()
    assert gate.accept(0) is True
    assert gate.accept(0) is False
    assert gate.accept(4) is True
    assert gate.accept(3) is False
    assert gate.current == 4


def test_latest_state_coalescing_never_regresses_generation():
    hidden = StateMessage(1, OverlayState.HIDDEN)
    recording = StateMessage(2, OverlayState.RECORDING)
    stale = StateMessage(1, OverlayState.ERROR)
    assert coalesce_latest_state(None, hidden) is hidden
    assert coalesce_latest_state(hidden, recording) is recording
    assert coalesce_latest_state(recording, stale) is recording


def test_error_timeout_is_guarded_by_generation_and_state():
    error = StateMessage(10, OverlayState.ERROR)
    assert error_timeout_applies(10, error) is True
    assert error_timeout_applies(9, error) is False
    assert error_timeout_applies(10, StateMessage(10, OverlayState.RECORDING)) is False


def test_null_sink_accepts_all_fixed_lifecycle_metadata():
    sink = NullStatusSink()
    sink.publish(OverlayState.RECORDING)
    sink.lifecycle(LifecycleEvent.MODEL_READY)
    sink.close()
