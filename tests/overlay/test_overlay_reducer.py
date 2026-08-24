# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure display-intent policy shared by every overlay helper backend.

The state machine used to exist twice (layer-shell and XWayland), covered only
through the real-XWayland smoke test.  These pin the transitions both backends
run, with the clock injected instead of read.
"""

from __future__ import annotations

import pytest

from stenographer.overlay.reducer import DisplayIntent, OverlayReducer
from stenographer.status import (
    SPECTRUM_BANDS,
    Command,
    CommandMessage,
    LoadingActivityMessage,
    OverlayState,
    ProtocolError,
    SpectrumMessage,
    StateMessage,
)

LOUD = (255,) * SPECTRUM_BANDS
SILENT = (0,) * SPECTRUM_BANDS


def _recording(reducer: OverlayReducer, *, generation: int = 0, now: float = 100.0) -> None:
    assert (
        reducer.apply(StateMessage(generation, OverlayState.RECORDING), now) is DisplayIntent.REDRAW
    )


def test_shutdown_stops_the_helper_and_leaves_the_surface_alone() -> None:
    reducer = OverlayReducer()
    _recording(reducer)

    assert reducer.apply(CommandMessage(Command.SHUTDOWN), 101.0) is DisplayIntent.STOP
    assert reducer.state is OverlayState.RECORDING


def test_unknown_command_and_record_types_are_protocol_errors() -> None:
    reducer = OverlayReducer()

    with pytest.raises(ProtocolError, match="command"):
        reducer.apply(CommandMessage("restart"), 100.0)
    with pytest.raises(ProtocolError, match="message"):
        reducer.apply(object(), 100.0)


def test_hidden_to_visible_redraws_and_hidden_tears_the_surface_down() -> None:
    reducer = OverlayReducer()

    assert reducer.state is OverlayState.HIDDEN
    _recording(reducer)
    assert reducer.visible is True
    assert reducer.apply(StateMessage(1, OverlayState.TRANSCRIBING), 101.0) is DisplayIntent.REDRAW
    assert reducer.apply(StateMessage(2, OverlayState.HIDDEN), 102.0) is DisplayIntent.TEARDOWN
    assert reducer.visible is False


def test_a_new_recording_never_inherits_the_previous_utterance_bars() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(SpectrumMessage(0, 0, LOUD), 100.5)
    assert reducer.levels == LOUD

    reducer.apply(StateMessage(1, OverlayState.HIDDEN), 101.0)
    _recording(reducer, generation=2, now=102.0)

    assert reducer.levels == SILENT


def test_spectrum_is_stored_but_only_the_recording_state_repaints() -> None:
    reducer = OverlayReducer()
    _recording(reducer)

    assert reducer.apply(SpectrumMessage(0, 0, LOUD), 100.5) is DisplayIntent.REPAINT

    reducer.apply(StateMessage(1, OverlayState.TRANSCRIBING), 101.0)

    assert reducer.apply(SpectrumMessage(0, 1, SILENT), 101.5) is DisplayIntent.NONE
    assert reducer.levels == SILENT
    assert reducer.levels_for(OverlayState.TRANSCRIBING) is None
    assert reducer.levels_for(OverlayState.RECORDING) == SILENT


def test_a_duplicate_loading_edge_never_restarts_the_breathing_phase() -> None:
    reducer = OverlayReducer()
    _recording(reducer)

    assert reducer.apply(LoadingActivityMessage(True), 100.5) is DisplayIntent.REPAINT
    started_at = reducer.pulse.started_at
    next_frame_at = reducer.pulse.next_frame_at

    assert reducer.apply(LoadingActivityMessage(True), 103.0) is DisplayIntent.NONE
    assert reducer.pulse.started_at == started_at
    assert reducer.pulse.next_frame_at == next_frame_at


def test_a_loading_edge_while_hidden_records_activity_without_drawing() -> None:
    reducer = OverlayReducer()

    assert reducer.apply(LoadingActivityMessage(True), 100.0) is DisplayIntent.NONE
    assert reducer.pulse.active is True
    assert reducer.pulse.next_frame_at is None

    # The pending pulse arms itself the moment a surface appears.
    _recording(reducer, now=101.0)
    assert reducer.pulse.next_frame_at is not None


def test_loading_off_repaints_the_visible_pill_without_arming_frames() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(True), 100.5)

    assert reducer.apply(LoadingActivityMessage(False), 101.0) is DisplayIntent.REPAINT
    assert reducer.pulse.active is False
    assert reducer.pulse.next_frame_at is None
    assert reducer.pulse.elapsed(102.0) is None


def test_hiding_disarms_loading_frames_but_keeps_the_activity_edge() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(True), 100.5)

    assert reducer.apply(StateMessage(1, OverlayState.HIDDEN), 101.0) is DisplayIntent.TEARDOWN
    assert reducer.pulse.next_frame_at is None
    assert reducer.pulse.active is True
    assert reducer.pulse.timeout(101.0, visible=False) is None


def test_a_visible_state_change_rearms_the_frame_cadence_from_now() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(True), 100.5)

    reducer.apply(StateMessage(1, OverlayState.TRANSCRIBING), 200.0)

    assert reducer.pulse.next_frame_at is not None
    assert reducer.pulse.next_frame_at > 200.0
    # The phase itself is anchored to the activity edge, not to the state.
    assert reducer.pulse.elapsed(200.0) == pytest.approx(99.5)


def test_one_utterance_drives_the_same_intents_for_either_backend() -> None:
    reducer = OverlayReducer()
    sequence = [
        (StateMessage(0, OverlayState.RECORDING), DisplayIntent.REDRAW),
        (SpectrumMessage(0, 0, LOUD), DisplayIntent.REPAINT),
        (LoadingActivityMessage(True), DisplayIntent.REPAINT),
        (StateMessage(1, OverlayState.TRANSCRIBING), DisplayIntent.REDRAW),
        (SpectrumMessage(1, 0, SILENT), DisplayIntent.NONE),
        (LoadingActivityMessage(False), DisplayIntent.REPAINT),
        (StateMessage(2, OverlayState.DELIVERING), DisplayIntent.REDRAW),
        (StateMessage(3, OverlayState.HIDDEN), DisplayIntent.TEARDOWN),
        (CommandMessage(Command.SHUTDOWN), DisplayIntent.STOP),
    ]

    intents = [reducer.apply(message, 100.0 + index) for index, (message, _) in enumerate(sequence)]

    assert intents == [expected for _message, expected in sequence]
