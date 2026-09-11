# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon policy behavior and regression coverage."""

from __future__ import annotations

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.contracts.publication import should_publish_state
from stenographer.lib.daemon.outcome import Outcome
from stenographer.lib.daemon.policy import (
    can_start,
    classify_pipeline,
    edge_handlers,
    hybrid_release_action,
    ignored_edge_reason,
    max_duration_applies,
    toggle_action,
)


class _EdgeSpy:
    """Stands in for a Daemon: edge_handlers only reads bound methods."""

    def on_key_down(self) -> None: ...

    def on_key_up(self) -> None: ...

    def on_toggle_press(self) -> None: ...

    def on_hybrid_release(self) -> None: ...


def test_gate_failure_is_silent():
    assert classify_pipeline(gate_passed=False, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_empty_transcript_is_silent():
    # Gate passed but the decode was empty/all-gated: success-shaped, no error.
    assert classify_pipeline(gate_passed=True, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_delivered_transcript():
    assert classify_pipeline(gate_passed=True, transcript_nonempty=True, deliver_result=True) == (
        Outcome.DELIVERED,
        None,
    )


def test_failed_delivery_is_error_with_message():
    outcome, message = classify_pipeline(
        gate_passed=True, transcript_nonempty=True, deliver_result=False
    )
    # A False deliver on non-empty text is never silent: the copy failed,
    # so the chord was withheld and the user must be told.
    assert outcome is Outcome.ERROR
    assert message


def test_ignored_edge_reason_names_the_state_that_refused_the_press():
    # Seen to FAIL against the single "recording_or_busy" reason this replaced,
    # which was true of every refusal and so explained none of them.
    assert ignored_edge_reason(recording=True, busy=True, stopping=True) == "recording"
    assert ignored_edge_reason(recording=False, busy=True, stopping=True) == "busy"
    assert ignored_edge_reason(recording=False, busy=False, stopping=True) == "stopping"
    assert ignored_edge_reason(recording=False, busy=False, stopping=False) == "none"


def test_can_start_only_when_fully_idle():
    assert can_start(recording=False, busy=False, stopping=False) is True
    assert can_start(recording=True, busy=False, stopping=False) is False
    assert can_start(recording=False, busy=True, stopping=False) is False
    assert can_start(recording=False, busy=False, stopping=True) is False


def test_toggle_action_maps_press_edges():
    # Idle press starts; a press while recording always stops, even during
    # shutdown, so a live capture is never stranded. A press during
    # transcription (busy) neither starts nor queues — one utterance at a time.
    assert toggle_action(recording=False, busy=False, stopping=False) == "start"
    assert toggle_action(recording=True, busy=False, stopping=False) == "stop"
    assert toggle_action(recording=False, busy=True, stopping=False) is None
    assert toggle_action(recording=False, busy=False, stopping=True) is None
    assert toggle_action(recording=True, busy=False, stopping=True) == "stop"


def test_hybrid_release_action_splits_a_tap_from_a_hold():
    # Seen to FAIL against a rule using ``>``: a release exactly at the
    # threshold latched instead of stopping. Pure: no daemon, no clock.
    assert hybrid_release_action(held_seconds=0.2, threshold=0.5) == "latch"
    assert hybrid_release_action(held_seconds=0.5, threshold=0.5) == "stop"
    assert hybrid_release_action(held_seconds=1.2, threshold=0.5) == "stop"


def test_max_duration_applies_guards_stale_generation():
    # A fired timer can be blocked on the state lock while a manual stop and an
    # immediate restart advance the generation; the stale timer must not stop
    # the newer recording, and a matching timer applies only while live.
    assert max_duration_applies(3, 3, recording=True) is True
    assert max_duration_applies(2, 3, recording=True) is False
    assert max_duration_applies(3, 3, recording=False) is False


def test_publish_policy_always_represents_error():
    # The helper auto-hides ERROR after a fixed timeout without notifying the
    # daemon, so the producer cache can be stale: a repeated ERROR (e.g. mic
    # failing twice in a row) must re-present rather than dedup away. Tested
    # against the name daemon.py binds in _publish_state. Seen to fail against
    # a dedup-only stub shadowing the helper.
    assert should_publish_state(OverlayState.ERROR, OverlayState.ERROR) is True


def test_publish_policy_dedups_stable_states():
    # Every non-ERROR state coalesces when repeated; any actual change passes.
    for state in OverlayState:
        if state is OverlayState.ERROR:
            continue
        assert should_publish_state(state, state) is False
    assert should_publish_state(OverlayState.HIDDEN, OverlayState.RECORDING) is True
    assert should_publish_state(OverlayState.RECORDING, OverlayState.TRANSCRIBING) is True
    assert should_publish_state(OverlayState.ERROR, OverlayState.HIDDEN) is True


def test_edge_handlers_map_mode_to_rising_and_falling_callbacks():
    # Seen to FAIL against a mapping that ignores the mode and returns the hold
    # pair for both. Pure: no platform, no listener, no device.
    daemon = _EdgeSpy()

    assert edge_handlers(daemon, "hold") == (daemon.on_key_down, daemon.on_key_up)

    on_start, on_stop = edge_handlers(daemon, "toggle")
    assert on_start == daemon.on_toggle_press
    # Only presses drive the session: the falling edge must be inert.
    assert on_stop not in (daemon.on_key_up, daemon.on_key_down)
    assert on_stop() is None

    on_start, on_stop = edge_handlers(daemon, "hybrid")
    assert on_start == daemon.on_toggle_press
    assert on_stop == daemon.on_hybrid_release
