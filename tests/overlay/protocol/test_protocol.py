# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for lifecycle/spectrum data and the versioned overlay protocol."""

from __future__ import annotations

import json

import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.codec import decode_message, encode_message
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.constants import (
    CANCELLED_DISPLAY_SECONDS,
    ERROR_DISPLAY_SECONDS,
    MAX_MESSAGE_BYTES,
)
from stenographer.overlay.protocol.display_message_gate import DisplayMessageGate
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.line_reader import LineReader
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    ReadyMessage,
    SpectrumMessage,
    StateMessage,
    UnavailableMessage,
)
from stenographer.overlay.protocol.ordering import (
    coalesce_spectrum_messages,
    drain_display_stream,
    transient_display_seconds,
    transient_timeout_applies,
)
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@pytest.mark.parametrize(
    "message",
    [
        StateMessage(generation=7, state=OverlayState.RECORDING),
        StateMessage(generation=8, state=OverlayState.CANCELLED),
        SpectrumMessage(generation=7, sequence=4, levels=tuple(range(SPECTRUM_BANDS))),
        LoadingActivityMessage(active=True),
        LoadingActivityMessage(active=False),
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


def test_protocol_uses_version_four_and_only_fixed_state_fields():
    encoded = encode_message(StateMessage(3, OverlayState.TRANSCRIBING))
    assert encoded == '{"v":4,"type":"state","generation":3,"state":"transcribing"}\n'
    assert "transcript" not in encoded
    assert "audio" not in encoded


@pytest.mark.parametrize(
    "record",
    [
        "",
        "not json\n",
        '{"v":1,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":2,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":3,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":4.0,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":4,"v":4,"type":"state","generation":0,"state":"hidden"}\n',
        '{"v":4,"type":"state","generation":0,"state":"hidden","state":"secret"}\n',
        '{"v":4,"type":"state","generation":true,"state":"hidden"}\n',
        '{"v":4,"type":"state","generation":-1,"state":"hidden"}\n',
        '{"v":4,"type":"state","generation":0,"state":"success"}\n',
        '{"v":4,"type":"state","generation":0,"state":"model_loading"}\n',
        '{"v":4,"type":"state","generation":0,"state":"hidden","text":"secret"}\n',
        '{"v":4,"type":"lifecycle","generation":1,"event":"model_ready"}\n',
        '{"v":4,"type":"lifecycle","generation":1,"event":"transcript_ready"}\n',
        '{"v":4,"type":"ready","backend":"gtk"}\n',
        '{"v":4,"type":"unavailable","reason":"a detailed display error"}\n',
        '{"v":4,"type":"command","command":"show_preview"}\n',
        '{"v":4,"type":"command","command":"shutdown"}\ntrailing',
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
    with pytest.raises(ProtocolError, match="levels"):
        encode_message(SpectrumMessage(1, 0, (0,) * (SPECTRUM_BANDS - 1)))
    with pytest.raises(ProtocolError, match="levels"):
        encode_message(SpectrumMessage(1, 0, (0,) * (SPECTRUM_BANDS - 1) + (256,)))
    with pytest.raises(ProtocolError, match="levels"):
        encode_message(SpectrumMessage(1, 0, (0,) * (SPECTRUM_BANDS - 1) + (True,)))
    with pytest.raises(ProtocolError, match="activity"):
        encode_message(LoadingActivityMessage(1))


def test_loading_activity_protocol_is_a_strict_boolean_only() -> None:
    assert encode_message(LoadingActivityMessage(True)) == (
        '{"v":4,"type":"loading_activity","active":true}\n'
    )
    assert encode_message(LoadingActivityMessage(False)) == (
        '{"v":4,"type":"loading_activity","active":false}\n'
    )
    for record in (
        '{"v":4,"type":"loading_activity","active":1}\n',
        '{"v":4,"type":"loading_activity","active":"true"}\n',
        '{"v":4,"type":"loading_activity","active":null}\n',
        '{"v":4,"type":"loading_activity","active":true,"phase":0}\n',
    ):
        with pytest.raises(ProtocolError, match=r"activity|fields"):
            decode_message(record)


@pytest.mark.parametrize(
    "record",
    [
        '{"v":4,"type":"spectrum","generation":3,"sequence":0,"levels":[0]}\n',
        '{"v":4,"type":"spectrum","generation":3,"sequence":0,"levels":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,256]}\n',
        '{"v":4,"type":"spectrum","generation":3,"sequence":0,"levels":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,true]}\n',
        '{"v":4,"type":"spectrum","generation":3,"sequence":false,"levels":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}\n',
        '{"v":4,"type":"spectrum","generation":3,"sequence":0,"levels":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"text":"secret"}\n',
    ],
)
def test_protocol_rejects_malformed_spectrum_records(record):
    with pytest.raises(ProtocolError) as exc:
        decode_message(record)
    assert "secret" not in str(exc.value)


def test_display_gate_rejects_stale_generations_and_unordered_spectrum():
    gate = DisplayMessageGate()
    recording = StateMessage(4, OverlayState.RECORDING)
    assert gate.accept(recording) is True
    assert gate.accept(SpectrumMessage(4, 0, (0,) * SPECTRUM_BANDS)) is True
    assert gate.accept(SpectrumMessage(4, 0, (1,) * SPECTRUM_BANDS)) is False
    assert gate.accept(SpectrumMessage(3, 1, (2,) * SPECTRUM_BANDS)) is False
    assert gate.accept(StateMessage(5, OverlayState.HIDDEN)) is True
    assert gate.accept(SpectrumMessage(4, 2, (3,) * SPECTRUM_BANDS)) is False
    assert gate.accept(SpectrumMessage(5, 3, (4,) * SPECTRUM_BANDS)) is False


def test_loading_activity_preserves_recording_generation_and_spectrum_order() -> None:
    gate = DisplayMessageGate()
    assert gate.accept(StateMessage(4, OverlayState.RECORDING)) is True
    assert gate.accept(SpectrumMessage(4, 0, (0,) * SPECTRUM_BANDS)) is True
    assert gate.accept(LoadingActivityMessage(True)) is True
    assert gate.loading_active is True
    assert gate.recording_generation == 4
    assert gate.accept(SpectrumMessage(4, 1, (1,) * SPECTRUM_BANDS)) is True
    assert gate.accept(LoadingActivityMessage(False)) is True
    assert gate.loading_active is False
    assert gate.accept(SpectrumMessage(4, 2, (2,) * SPECTRUM_BANDS)) is True


def test_spectrum_coalescing_keeps_latest_adjacent_frame_and_ordering_barriers():
    state = StateMessage(3, OverlayState.RECORDING)
    first = SpectrumMessage(3, 0, (1,) * SPECTRUM_BANDS)
    latest = SpectrumMessage(3, 1, (2,) * SPECTRUM_BANDS)
    loading = LoadingActivityMessage(True)
    hidden = StateMessage(4, OverlayState.HIDDEN)

    assert coalesce_spectrum_messages((state, first, latest, loading, first, hidden)) == (
        state,
        latest,
        loading,
        first,
        hidden,
    )


def test_incremental_line_reader_frames_only_complete_bounded_records():
    record = encode_message(StateMessage(2, OverlayState.RECORDING)).encode()
    reader = LineReader()

    assert reader.feed(record[:7]) == []
    assert reader.feed(record[7:]) == [record]
    reader.finish()


def test_incremental_line_reader_rejects_oversize_and_truncated_records():
    reader = LineReader()
    with pytest.raises(ProtocolError, match="too large"):
        reader.feed(b"x" * MAX_MESSAGE_BYTES)

    reader = LineReader()
    reader.feed(b'{"v":4')
    with pytest.raises(ProtocolError, match="mid-record"):
        reader.finish()


def _drain_context() -> tuple[LineReader, DisplayMessageGate]:
    return LineReader(), DisplayMessageGate()


def test_drain_display_stream_frames_records_split_across_chunks():
    reader, gate = _drain_context()
    first = encode_message(StateMessage(1, OverlayState.RECORDING)).encode()
    second = encode_message(SpectrumMessage(1, 0, (7,) * SPECTRUM_BANDS)).encode()
    stream = first + second

    assert drain_display_stream(stream[:9], reader, gate) == ()
    assert drain_display_stream(stream[9:], reader, gate) == (
        StateMessage(1, OverlayState.RECORDING),
        SpectrumMessage(1, 0, (7,) * SPECTRUM_BANDS),
    )
    reader.finish()


def test_drain_display_stream_rejects_stale_generations_through_the_gate():
    reader, gate = _drain_context()
    stream = (
        encode_message(StateMessage(5, OverlayState.RECORDING))
        + encode_message(StateMessage(3, OverlayState.TRANSCRIBING))
        + encode_message(SpectrumMessage(3, 0, (1,) * SPECTRUM_BANDS))
    ).encode()

    assert drain_display_stream(stream, reader, gate) == (StateMessage(5, OverlayState.RECORDING),)


def test_drain_display_stream_coalesces_adjacent_spectrum_frames_only():
    reader, gate = _drain_context()
    stream = (
        encode_message(StateMessage(2, OverlayState.RECORDING))
        + encode_message(SpectrumMessage(2, 0, (1,) * SPECTRUM_BANDS))
        + encode_message(SpectrumMessage(2, 1, (2,) * SPECTRUM_BANDS))
        + encode_message(LoadingActivityMessage(True))
        + encode_message(SpectrumMessage(2, 2, (3,) * SPECTRUM_BANDS))
        + encode_message(CommandMessage(Command.SHUTDOWN))
    ).encode()

    assert drain_display_stream(stream, reader, gate) == (
        StateMessage(2, OverlayState.RECORDING),
        SpectrumMessage(2, 1, (2,) * SPECTRUM_BANDS),
        LoadingActivityMessage(True),
        SpectrumMessage(2, 2, (3,) * SPECTRUM_BANDS),
        CommandMessage(Command.SHUTDOWN),
    )


def test_drain_display_stream_rejects_malformed_and_oversize_lines():
    reader, gate = _drain_context()
    with pytest.raises(ProtocolError, match="not valid JSON"):
        drain_display_stream(b"{broken\n", reader, gate)

    reader, gate = _drain_context()
    with pytest.raises(ProtocolError, match="too large"):
        drain_display_stream(b"x" * MAX_MESSAGE_BYTES, reader, gate)


def test_drain_display_stream_rejects_unexpected_parent_message_types():
    reader, gate = _drain_context()
    stream = encode_message(ReadyMessage(Backend.XWAYLAND)).encode()
    with pytest.raises(ProtocolError, match="unexpected parent protocol message"):
        drain_display_stream(stream, reader, gate)


def test_transient_timeout_is_guarded_by_generation_and_state():
    error = StateMessage(10, OverlayState.ERROR)
    cancelled = StateMessage(11, OverlayState.CANCELLED)
    assert transient_timeout_applies(10, error) is True
    assert transient_timeout_applies(9, error) is False
    assert transient_timeout_applies(11, cancelled) is True
    assert transient_timeout_applies(10, StateMessage(10, OverlayState.RECORDING)) is False


def test_transient_display_windows_match_the_visual_contract():
    assert transient_display_seconds(OverlayState.ERROR) == ERROR_DISPLAY_SECONDS
    assert transient_display_seconds(OverlayState.CANCELLED) == CANCELLED_DISPLAY_SECONDS
    assert transient_display_seconds(OverlayState.HIDDEN) is None


@pytest.mark.parametrize(
    ("message", "match"),
    [
        (SpectrumMessage(-1, 0, (0,) * SPECTRUM_BANDS), "generation"),
        (SpectrumMessage(0, True, (0,) * SPECTRUM_BANDS), "sequence"),
        (SpectrumMessage(0, 0, [0] * SPECTRUM_BANDS), "levels"),
        (CommandMessage("shutdown"), "command"),
        (ReadyMessage("xwayland"), "backend"),
        (UnavailableMessage("no_x_display"), "unavailable reason"),
        (object(), "unsupported protocol message type"),
    ],
)
def test_the_encoder_refuses_anything_it_cannot_describe_exactly(message, match):
    """A str subclass is not a ``Backend``: accepting one would put a value on
    the wire that the other end's enum lookup has never heard of.
    """
    with pytest.raises(ProtocolError, match=match):
        encode_message(message)


@pytest.mark.parametrize(
    ("record", "match"),
    [
        ('{"v":4,"type":"state","generation":0,"state":7}\n', "state has wrong type"),
        ('{"v":4,"type":"command","command":null}\n', "command has wrong type"),
        ('{"v":4,"type":"ready","backend":4}\n', "backend has wrong type"),
        ('{"v":4,"type":"unavailable","reason":[]}\n', "reason has wrong type"),
        ('{"v":4,"type":"ready","backend":"quartz"}\n', "backend has unknown value"),
        ('{"v":4,"type":"command","command":"restart"}\n', "command has unknown value"),
        ('{"v":4,"type":"unavailable","reason":"bored"}\n', "reason has unknown value"),
    ],
)
def test_the_decoder_separates_a_wrong_type_from_an_unknown_value(record, match):
    """Both are refusals, but only the second one means the peer is newer."""
    with pytest.raises(ProtocolError, match=match):
        decode_message(record)


@pytest.mark.parametrize(
    ("generation", "sequence", "match"),
    [(-1, 0, "generation"), (0, -1, "sequence"), (True, 0, "generation")],
)
def test_the_decoder_rejects_spectrum_counters_outside_the_wire_range(generation, sequence, match):
    levels = str([0] * SPECTRUM_BANDS).replace(" ", "")
    record = (
        f'{{"v":4,"type":"spectrum","generation":{json.dumps(generation)},'
        f'"sequence":{json.dumps(sequence)},"levels":{levels}}}\n'
    )

    with pytest.raises(ProtocolError, match=match):
        decode_message(record)


def test_the_decoder_rejects_oversize_bytes_before_decoding_them():
    with pytest.raises(ProtocolError, match="too large"):
        decode_message(b"x" * (MAX_MESSAGE_BYTES + 1))


def test_the_decoder_rejects_bytes_that_are_not_utf_eight():
    with pytest.raises(ProtocolError, match="not UTF-8"):
        decode_message(b'{"v":4,"type":"ready","backend":"\xff\xfe"}\n')


@pytest.mark.parametrize("record", [4, None, ["state"], {"v": 4}])
def test_the_decoder_only_accepts_text_or_bytes(record):
    with pytest.raises(ProtocolError, match="record has wrong type"):
        decode_message(record)


@pytest.mark.parametrize("record", ["[1,2,3]\n", '"state"\n', "4\n", "null\n"])
def test_a_json_value_that_is_not_an_object_is_not_a_record(record):
    with pytest.raises(ProtocolError, match=r"not an object|unsupported protocol version"):
        decode_message(record)


def test_the_display_gate_only_accepts_the_three_generated_display_records():
    """A command reaching the gate would be silently gated on a generation it
    does not have; it belongs on the ordering path beside the gate, not in it.
    """
    gate = DisplayMessageGate()

    with pytest.raises(TypeError, match="generated display messages"):
        gate.accept(CommandMessage(Command.SHUTDOWN))


@pytest.mark.parametrize("generation", [-1, True, 1.0])
def test_the_display_gate_refuses_a_generation_it_cannot_order(generation):
    gate = DisplayMessageGate()

    with pytest.raises(ValueError, match="non-negative signed 64-bit integer"):
        gate.accept(StateMessage(generation, OverlayState.RECORDING))


def test_an_empty_read_frames_nothing_and_leaves_the_buffer_untouched():
    """A selector can report a descriptor readable and yield nothing; that must
    not be mistaken for a completed record.
    """
    reader = LineReader()
    reader.feed(b'{"v":4')

    assert reader.feed(b"") == []

    with pytest.raises(ProtocolError, match="mid-record"):
        reader.finish()


def test_a_complete_but_oversize_line_is_rejected_as_it_is_framed():
    reader = LineReader()

    with pytest.raises(ProtocolError, match="too large"):
        reader.feed(b"x" * MAX_MESSAGE_BYTES + b"\n")


def test_finishing_an_empty_reader_is_a_clean_end_of_stream():
    LineReader().finish()
