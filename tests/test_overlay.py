# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for overlay supervision policy (no child processes)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from stenographer.overlay import (
    _POLL_SECONDS,
    _SPECTRUM_INTERVAL,
    OutboundMailbox,
    RestartBudget,
    helper_command,
    helper_ready_timed_out,
    schedule_spectrum,
    serve_timeout,
)
from stenographer.status import (
    SPECTRUM_BANDS,
    Command,
    CommandMessage,
    LoadingActivityMessage,
    OverlayState,
    SpectrumMessage,
    StateMessage,
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


def test_mailbox_error_timeout_enqueues_a_generation_guarded_hide():
    mailbox = OutboundMailbox()
    error_generation = mailbox.publish(OverlayState.ERROR)
    deadline = mailbox.error_deadline
    assert deadline is not None
    assert mailbox.take_nowait() == StateMessage(error_generation, OverlayState.ERROR)

    assert mailbox.expire_error(deadline - 0.001) is None
    hide_generation = mailbox.expire_error(deadline)

    assert hide_generation == error_generation + 1
    assert mailbox.take_nowait() == StateMessage(hide_generation, OverlayState.HIDDEN)


def test_restart_budget_allows_exactly_one_unexpected_restart():
    budget = RestartBudget(1)

    assert budget.on_exit(unexpected=True) is True
    assert budget.on_exit(unexpected=True) is False
    assert budget.on_exit(unexpected=True) is False


def test_expected_exit_never_spends_or_uses_restart_budget():
    budget = RestartBudget(1)

    assert budget.on_exit(unexpected=False) is False
    assert budget.on_exit(unexpected=True) is True
