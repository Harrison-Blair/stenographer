# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for lifecycle/spectrum data and the versioned overlay protocol."""

from __future__ import annotations

import pytest

from stenographer.status import (
    MAX_MESSAGE_BYTES,
    SPECTRUM_BANDS,
    Backend,
    Command,
    CommandMessage,
    DisplayMessageGate,
    LineReader,
    LoadingActivityMessage,
    NullStatusSink,
    OverlayState,
    ProtocolError,
    ReadyMessage,
    SpectrumMessage,
    StateMessage,
    UnavailableMessage,
    UnavailableReason,
    coalesce_spectrum_messages,
    decode_message,
    drain_display_stream,
    encode_message,
    error_timeout_applies,
    should_publish_state,
)


@pytest.mark.parametrize(
    "message",
    [
        StateMessage(generation=7, state=OverlayState.RECORDING),
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


def test_visible_state_set_has_no_loading_pill() -> None:
    assert tuple(OverlayState) == (
        OverlayState.HIDDEN,
        OverlayState.RECORDING,
        OverlayState.TRANSCRIBING,
        OverlayState.DELIVERING,
        OverlayState.ERROR,
    )


def test_state_publication_repeats_errors_but_suppresses_other_duplicates() -> None:
    assert should_publish_state(OverlayState.RECORDING, OverlayState.TRANSCRIBING) is True
    assert should_publish_state(OverlayState.RECORDING, OverlayState.RECORDING) is False
    assert should_publish_state(OverlayState.ERROR, OverlayState.ERROR) is True


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


def test_error_timeout_is_guarded_by_generation_and_state():
    error = StateMessage(10, OverlayState.ERROR)
    assert error_timeout_applies(10, error) is True
    assert error_timeout_applies(9, error) is False
    assert error_timeout_applies(10, StateMessage(10, OverlayState.RECORDING)) is False


def test_null_sink_accepts_all_fixed_display_metadata():
    sink = NullStatusSink()
    sink.publish(OverlayState.RECORDING)
    sink.loading_activity(True)
    sink.loading_activity(False)
    sink.audio_block(object(), 16000, 4)
    sink.close()
