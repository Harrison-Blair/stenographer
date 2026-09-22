# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure display-intent policy shared by every overlay helper backend.

The state machine used to exist twice (layer-shell and XWayland), covered only
through the real-XWayland smoke test.  These pin the transitions both backends
run, with the clock injected instead of read.
"""

from __future__ import annotations

import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.errors import ProtocolError
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.rendering.display_intent import DisplayIntent
from stenographer.overlay.rendering.reducer import OverlayReducer

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

    assert (
        reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)
        is DisplayIntent.REPAINT
    )
    breath_started_at = reducer.pulse.breath_started_at
    next_frame_at = reducer.pulse.next_frame_at

    assert (
        reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 103.0) is DisplayIntent.NONE
    )
    assert reducer.pulse.breath_started_at == breath_started_at
    assert reducer.pulse.next_frame_at == next_frame_at


def test_a_loading_edge_while_hidden_records_activity_without_drawing() -> None:
    reducer = OverlayReducer()

    assert (
        reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.0) is DisplayIntent.NONE
    )
    assert reducer.pulse.loading == [LoadingModel.ASR]
    assert reducer.pulse.breathing is False

    # The pending pulse starts breathing the moment a surface appears.
    _recording(reducer, now=101.0)
    assert reducer.pulse.breathing is True
    assert reducer.pulse.breath_model is LoadingModel.ASR
    assert reducer.pulse.breath_started_at == 101.0


def test_loading_off_lets_the_current_breath_finish_before_the_border_goes() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)

    assert (
        reducer.apply(LoadingActivityMessage(LoadingModel.ASR, False), 101.0) is DisplayIntent.NONE
    )
    assert reducer.pulse.breathing is True
    assert reducer.pulse.next_frame_at is not None

    reducer.pulse.advance(reducer.pulse.breath_started_at + 2.0)

    assert reducer.pulse.breathing is False
    assert reducer.pulse.elapsed(105.0) is None
    assert reducer.pulse.timeout(105.0, visible=True) is None


def test_hiding_disarms_loading_frames_but_keeps_the_activity_edge() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)

    assert reducer.apply(StateMessage(1, OverlayState.HIDDEN), 101.0) is DisplayIntent.TEARDOWN
    assert reducer.pulse.next_frame_at is None
    assert reducer.pulse.breathing is False
    assert reducer.pulse.loading == [LoadingModel.ASR]
    assert reducer.pulse.timeout(101.0, visible=False) is None


def test_a_visible_state_change_rearms_the_frame_cadence_from_now() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)

    reducer.apply(StateMessage(1, OverlayState.TRANSCRIBING), 200.0)

    assert reducer.pulse.next_frame_at is not None
    assert reducer.pulse.next_frame_at > 200.0
    # The breath itself is kept across a visible state change, not restarted.
    assert reducer.pulse.breath_model is LoadingModel.ASR
    assert reducer.pulse.breath_started_at == 100.5


def test_a_second_model_joining_repaints_nothing_until_its_breath() -> None:
    reducer = OverlayReducer()
    _recording(reducer)
    reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)

    assert (
        reducer.apply(LoadingActivityMessage(LoadingModel.REFINE, True), 100.8)
        is DisplayIntent.NONE
    )
    assert reducer.pulse.loading == [LoadingModel.ASR, LoadingModel.REFINE]
    assert reducer.pulse.breath_model is LoadingModel.ASR
    assert reducer.pulse.breath_started_at == 100.5


def test_a_show_after_a_hide_starts_the_aura_at_the_trough_with_the_earliest_model() -> None:
    reducer = OverlayReducer()
    reducer.apply(LoadingActivityMessage(LoadingModel.REFINE, True), 100.0)
    reducer.apply(LoadingActivityMessage(LoadingModel.ASR, True), 100.5)

    assert reducer.apply(StateMessage(0, OverlayState.TRANSCRIBING), 300.0) is DisplayIntent.REDRAW

    assert reducer.pulse.breath_model is LoadingModel.REFINE
    assert reducer.pulse.elapsed(300.0) == 0.0


def test_one_utterance_drives_the_same_intents_for_either_backend() -> None:
    reducer = OverlayReducer()
    sequence = [
        (StateMessage(0, OverlayState.RECORDING), DisplayIntent.REDRAW),
        (SpectrumMessage(0, 0, LOUD), DisplayIntent.REPAINT),
        (LoadingActivityMessage(LoadingModel.ASR, True), DisplayIntent.REPAINT),
        (StateMessage(1, OverlayState.TRANSCRIBING), DisplayIntent.REDRAW),
        (SpectrumMessage(1, 0, SILENT), DisplayIntent.NONE),
        (LoadingActivityMessage(LoadingModel.ASR, False), DisplayIntent.NONE),
        (StateMessage(2, OverlayState.DELIVERING), DisplayIntent.REDRAW),
        (StateMessage(3, OverlayState.HIDDEN), DisplayIntent.TEARDOWN),
        (CommandMessage(Command.SHUTDOWN), DisplayIntent.STOP),
    ]

    intents = [reducer.apply(message, 100.0 + index) for index, (message, _) in enumerate(sequence)]

    assert intents == [expected for _message, expected in sequence]
