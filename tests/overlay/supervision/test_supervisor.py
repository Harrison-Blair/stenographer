# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for overlay supervision policy (no child processes).

The mailbox's blocking ``take`` is the one exception: two real threads, because
a queue that never wakes its consumer is exactly the bug worth catching.
"""

from __future__ import annotations

import logging
import threading
import time
from itertools import pairwise

import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.overlay.protocol.command import Command
from stenographer.overlay.protocol.messages import (
    CommandMessage,
    LoadingActivityMessage,
    SpectrumMessage,
    StateMessage,
)
from stenographer.overlay.supervision.constants import _POLL_SECONDS, _SPECTRUM_INTERVAL
from stenographer.overlay.supervision.models import RestartBudget, _ProcessOutcome
from stenographer.overlay.supervision.outbound_mailbox import OutboundMailbox
from stenographer.overlay.supervision.policy import (
    _helper_stderr_path,
    helper_command,
    helper_ready_timed_out,
    schedule_spectrum,
    serve_timeout,
)


def test_helper_command_uses_module_reexec_for_source_install():
    assert helper_command("/venv/bin/python", frozen=False) == (
        "/venv/bin/python",
        "-m",
        "stenographer.cli",
        "_overlay",
    )


def test_helper_command_uses_frozen_entry_point():
    assert helper_command("/opt/stenographer/stenographer", frozen=True) == (
        "/opt/stenographer/stenographer",
        "_overlay",
    )


def test_helper_readiness_deadline_is_bounded_and_guarded_by_ready_state():
    assert helper_ready_timed_out(started_at=10.0, now=12.9, ready=False) is False
    assert helper_ready_timed_out(started_at=10.0, now=13.0, ready=False) is True
    assert helper_ready_timed_out(started_at=10.0, now=99.0, ready=True) is False


def test_schedule_spectrum_stays_disarmed_while_not_recording():
    assert schedule_spectrum(False, None, 100.0) == (None, False)


def test_schedule_spectrum_runs_one_cleanup_produce_on_leaving_recording():
    assert schedule_spectrum(False, 100.02, 100.0) == (None, True)
    assert schedule_spectrum(False, 99.0, 100.0) == (None, True)


def test_schedule_spectrum_produces_immediately_on_entering_recording():
    assert schedule_spectrum(True, None, 100.0) == (100.0 + _SPECTRUM_INTERVAL, True)


def test_schedule_spectrum_produces_and_rearms_when_deadline_is_due():
    assert schedule_spectrum(True, 100.0, 100.0) == (100.0 + _SPECTRUM_INTERVAL, True)
    assert schedule_spectrum(True, 99.5, 100.0) == (100.0 + _SPECTRUM_INTERVAL, True)


def test_schedule_spectrum_keeps_a_pending_deadline_untouched():
    assert schedule_spectrum(True, 100.02, 100.0) == (100.02, False)


def test_serve_timeout_idles_at_poll_cadence_without_a_deadline():
    assert serve_timeout(100.0, None) == _POLL_SECONDS


def test_serve_timeout_clamps_imminent_and_past_deadlines_to_zero_or_more():
    assert serve_timeout(100.0, 100.01) == pytest.approx(0.01)
    assert serve_timeout(100.0, 99.0) == 0.0


def test_serve_timeout_caps_far_deadlines_at_poll_cadence():
    assert serve_timeout(100.0, 200.0, poll_seconds=0.05) == 0.05


def test_mailbox_assigns_generations_and_coalesces_pending_states():
    mailbox = OutboundMailbox()

    assert mailbox.publish(OverlayState.RECORDING) == 0
    assert mailbox.publish(OverlayState.TRANSCRIBING) == 1
    assert mailbox.take_nowait() == StateMessage(1, OverlayState.TRANSCRIBING)
    assert mailbox.take_nowait() is None


def test_mailbox_coalesces_audio_and_spectrum_into_latest_only_slots():
    mailbox = OutboundMailbox()
    generation = mailbox.publish(OverlayState.RECORDING)
    assert mailbox.take_nowait() == StateMessage(generation, OverlayState.RECORDING)
    first = object()
    latest = object()
    mailbox.audio_block(first, 16000, 11)
    mailbox.audio_block(latest, 16000, 11)

    block = mailbox.take_audio_nowait()
    assert block is not None
    assert block.samples is latest
    assert block.generation == generation
    assert block.stream_epoch == 11
    assert mailbox.take_audio_nowait() is None

    assert mailbox.publish_spectrum(generation, (1,) * SPECTRUM_BANDS) == 0
    assert mailbox.publish_spectrum(generation, (2,) * SPECTRUM_BANDS) == 1
    assert mailbox.take_nowait() == SpectrumMessage(generation, 1, (2,) * SPECTRUM_BANDS)
    assert mailbox.take_nowait() is None


def test_loading_activity_is_ordered_without_resetting_recording_slots():
    mailbox = OutboundMailbox()
    generation = mailbox.publish(OverlayState.RECORDING)
    assert mailbox.take_nowait() == StateMessage(generation, OverlayState.RECORDING)
    mailbox.audio_block(object(), 16000, 11)
    assert mailbox.publish_spectrum(generation, (1,) * SPECTRUM_BANDS) == 0

    mailbox.loading_activity(True)

    assert mailbox.take_nowait() == LoadingActivityMessage(True)
    block = mailbox.take_audio_nowait()
    assert block is not None and block.generation == generation
    assert mailbox.take_nowait() == SpectrumMessage(generation, 0, (1,) * SPECTRUM_BANDS)
    assert mailbox.publish_spectrum(generation, (2,) * SPECTRUM_BANDS) == 1

    mailbox.loading_activity(False)
    assert mailbox.take_nowait() == LoadingActivityMessage(False)
    assert mailbox.take_nowait() == SpectrumMessage(generation, 1, (2,) * SPECTRUM_BANDS)


def test_loading_activity_requires_a_strict_boolean():
    mailbox = OutboundMailbox()
    with pytest.raises(TypeError, match="boolean"):
        mailbox.loading_activity(1)


def test_mailbox_transition_discards_prior_recording_frames_and_takes_priority():
    mailbox = OutboundMailbox()
    recording = mailbox.publish(OverlayState.RECORDING)
    assert mailbox.take_nowait() == StateMessage(recording, OverlayState.RECORDING)
    mailbox.audio_block(object(), 16000, 11)
    mailbox.publish_spectrum(recording, (255,) * SPECTRUM_BANDS)

    hidden = mailbox.publish(OverlayState.HIDDEN)

    assert mailbox.take_audio_nowait() is None
    assert mailbox.take_nowait() == StateMessage(hidden, OverlayState.HIDDEN)
    assert mailbox.take_nowait() is None
    assert mailbox.publish_spectrum(recording, (128,) * SPECTRUM_BANDS) is None


def test_mailbox_is_bounded_and_keeps_newest_metadata():
    mailbox = OutboundMailbox(capacity=3)
    mailbox.publish(OverlayState.RECORDING)
    mailbox.loading_activity(True)
    mailbox.publish(OverlayState.TRANSCRIBING)
    mailbox.loading_activity(False)
    mailbox.publish(OverlayState.DELIVERING)
    mailbox.publish(OverlayState.ERROR)

    messages = []
    while (message := mailbox.take_nowait()) is not None:
        messages.append(message)

    assert len(messages) <= 3
    assert messages[-1] == StateMessage(3, OverlayState.ERROR)
    generated = [message for message in messages if isinstance(message, StateMessage)]
    assert all(a.generation < b.generation for a, b in pairwise(generated))


def test_mailbox_close_is_idempotent_and_shutdown_takes_priority():
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)
    mailbox.close()
    mailbox.close()

    assert mailbox.take_nowait() == CommandMessage(Command.SHUTDOWN)
    assert mailbox.take_nowait() is None


def test_mailbox_remembers_latest_state_for_helper_restart():
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)
    mailbox.publish(OverlayState.TRANSCRIBING)
    mailbox.take_nowait()

    assert mailbox.current_state == StateMessage(1, OverlayState.TRANSCRIBING)


def test_helper_replay_uses_current_state_and_active_loading_only():
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)
    mailbox.loading_activity(True)
    mailbox.publish(OverlayState.TRANSCRIBING)

    assert mailbox.replay_for_helper() == (
        LoadingActivityMessage(True),
        StateMessage(1, OverlayState.TRANSCRIBING),
    )
    assert mailbox.take_nowait() is None

    mailbox.loading_activity(False)
    assert mailbox.replay_for_helper() == (StateMessage(1, OverlayState.TRANSCRIBING),)
    assert mailbox.take_nowait() is None


def test_mailbox_transient_timeout_enqueues_a_generation_guarded_hide():
    mailbox = OutboundMailbox()
    error_generation = mailbox.publish(OverlayState.ERROR)
    deadline = mailbox.transient_deadline
    assert deadline is not None
    assert mailbox.take_nowait() == StateMessage(error_generation, OverlayState.ERROR)

    assert mailbox.expire_transient(deadline - 0.001) is None
    hide_generation = mailbox.expire_transient(deadline)

    assert hide_generation == error_generation + 1
    assert mailbox.take_nowait() == StateMessage(hide_generation, OverlayState.HIDDEN)


def test_mailbox_cancelled_timeout_is_short_and_generation_guarded():
    mailbox = OutboundMailbox()
    cancelled_generation = mailbox.publish(OverlayState.CANCELLED)
    deadline = mailbox.transient_deadline
    assert deadline is not None
    assert mailbox.expire_transient(deadline - 0.001) is None
    hide_generation = mailbox.expire_transient(deadline)

    assert hide_generation == cancelled_generation + 1
    assert mailbox.take_nowait() == StateMessage(hide_generation, OverlayState.HIDDEN)

    newer = mailbox.publish(OverlayState.RECORDING)
    assert mailbox.expire_transient(deadline + 100.0) is None
    assert mailbox.current_state == StateMessage(newer, OverlayState.RECORDING)


def test_restart_budget_allows_exactly_one_unexpected_restart():
    budget = RestartBudget(1)

    assert budget.on_exit(unexpected=True) is True
    assert budget.on_exit(unexpected=True) is False
    assert budget.on_exit(unexpected=True) is False


def test_expected_exit_never_spends_or_uses_restart_budget():
    budget = RestartBudget(1)

    assert budget.on_exit(unexpected=False) is False
    assert budget.on_exit(unexpected=True) is True


@pytest.mark.parametrize("capacity", [0, -1, True, False, 8.0, "8"])
def test_mailbox_capacity_must_be_a_real_positive_integer(capacity: object) -> None:
    """``True`` is an ``int`` in Python: a bool capacity would silently make a
    one-slot mailbox that drops every record but the newest.
    """
    with pytest.raises(ValueError, match="positive integer"):
        OutboundMailbox(capacity=capacity)


def test_mailbox_publish_requires_a_real_overlay_state() -> None:
    with pytest.raises(TypeError, match="OverlayState"):
        OutboundMailbox().publish("recording")


def test_a_closed_mailbox_accepts_nothing_but_still_reports_the_last_state() -> None:
    """The daemon keeps calling the sink while it shuts down; those calls must
    neither raise nor displace the shutdown command already queued.
    """
    mailbox = OutboundMailbox()
    recording = mailbox.publish(OverlayState.RECORDING)
    mailbox.close()

    assert mailbox.publish(OverlayState.ERROR) == recording
    mailbox.loading_activity(True)
    mailbox.audio_block(object(), 16000, 0)

    assert mailbox.take_nowait() == CommandMessage(Command.SHUTDOWN)
    assert mailbox.take_nowait() is None
    assert mailbox.take_audio_nowait() is None


def test_disabling_discards_every_optional_record_and_stops_accepting_more() -> None:
    """Once the helper is permanently gone the daemon must not accumulate
    frames nobody will ever read.
    """
    mailbox = OutboundMailbox()
    generation = mailbox.publish(OverlayState.RECORDING)
    mailbox.audio_block(object(), 16000, 0)
    mailbox.publish_spectrum(generation, (9,) * SPECTRUM_BANDS)

    mailbox.disable()

    assert mailbox.take_nowait() is None
    assert mailbox.take_audio_nowait() is None
    assert mailbox.publish(OverlayState.ERROR) == generation
    mailbox.loading_activity(True)
    mailbox.audio_block(object(), 16000, 0)
    assert mailbox.take_nowait() is None
    assert mailbox.take_audio_nowait() is None


@pytest.mark.parametrize("sample_rate", [0, -1, True, 16000.0])
def test_audio_blocks_with_an_unusable_sample_rate_are_dropped(sample_rate: object) -> None:
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)

    mailbox.audio_block(object(), sample_rate, 0)

    assert mailbox.take_audio_nowait() is None


@pytest.mark.parametrize("stream_epoch", [-1, True, 0.0])
def test_audio_blocks_with_an_unusable_stream_epoch_are_dropped(stream_epoch: object) -> None:
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)

    mailbox.audio_block(object(), 16000, stream_epoch)

    assert mailbox.take_audio_nowait() is None


def test_audio_arriving_outside_a_recording_is_dropped_rather_than_tagged() -> None:
    """There is no generation to tag it with, and an untagged block would be
    replayed into whatever recording starts next.
    """
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.TRANSCRIBING)

    mailbox.audio_block(object(), 16000, 0)

    assert mailbox.take_audio_nowait() is None


def test_a_duplicate_loading_edge_queues_nothing() -> None:
    mailbox = OutboundMailbox()
    mailbox.loading_activity(True)
    assert mailbox.take_nowait() == LoadingActivityMessage(True)

    mailbox.loading_activity(True)

    assert mailbox.take_nowait() is None


def test_expire_transient_reads_the_clock_when_the_caller_does_not() -> None:
    """The supervisor calls it with no argument on every loop turn."""
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.RECORDING)

    assert mailbox.expire_transient() is None
    assert mailbox.current_state.state is OverlayState.RECORDING


def test_a_blocking_take_wakes_on_the_next_published_record() -> None:
    """The supervisor's wait has to end when work arrives, not when it expires.

    Seen to FAIL against a ``take`` that waited without being notified: the
    first state change of a session would be delayed by the whole timeout.
    """
    mailbox = OutboundMailbox()
    taken: list[object] = []
    ready = threading.Event()

    def consume() -> None:
        ready.set()
        taken.append(mailbox.take(timeout=10.0))

    consumer = threading.Thread(target=consume, name="mailbox-take")
    consumer.start()
    try:
        assert ready.wait(10.0)
        started = time.monotonic()
        mailbox.publish(OverlayState.DELIVERING)
        consumer.join(timeout=10.0)
    finally:
        consumer.join(timeout=10.0)

    assert not consumer.is_alive()
    assert taken == [StateMessage(0, OverlayState.DELIVERING)]
    assert time.monotonic() - started < 5.0


def test_a_blocking_take_returns_nothing_once_its_timeout_expires() -> None:
    mailbox = OutboundMailbox()

    assert mailbox.take(timeout=0.01) is None


def test_a_blocking_take_returns_a_waiting_record_without_waiting() -> None:
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.ERROR)

    assert mailbox.take(timeout=10.0) == StateMessage(0, OverlayState.ERROR)


@pytest.mark.parametrize("remaining", [-1, True])
def test_a_restart_budget_must_be_a_real_non_negative_count(remaining: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        RestartBudget(remaining)


def test_a_process_outcome_is_only_unavailable_when_the_helper_said_so() -> None:
    """An expected exit is not the same as an overlay that cannot exist: only
    the second one stops the supervisor from ever trying again.
    """
    assert _ProcessOutcome(True).unavailable is False
    assert _ProcessOutcome(False, True).unavailable is True


def test_the_helper_stderr_file_is_created_under_the_state_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    path = _helper_stderr_path()

    assert path is not None
    assert path.name == "overlay-helper.log"
    assert path.parent.is_dir()


def test_an_unusable_state_directory_costs_the_diagnostics_not_the_overlay(
    tmp_path, monkeypatch, caplog
) -> None:
    """Seen to matter on a machine whose state path is occupied by a file: a
    helper that refused to start over its own log would disable the overlay.
    """
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(occupied))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(logging.getLogger("stenographer"), "propagate", True)

    with caplog.at_level(logging.DEBUG, logger="stenographer.overlay.supervision.constants"):
        assert _helper_stderr_path() is None

    assert any("helper_log_unavailable" in record.getMessage() for record in caplog.records), [
        record.getMessage() for record in caplog.records
    ]
