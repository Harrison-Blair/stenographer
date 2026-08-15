# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for overlay supervision policy (no child processes)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from stenographer.overlay import (
    OutboundMailbox,
    RestartBudget,
    _LineReader,
    helper_command,
    helper_ready_timed_out,
)
from stenographer.status import (
    MAX_MESSAGE_BYTES,
    Command,
    CommandMessage,
    LifecycleEvent,
    LifecycleMessage,
    OverlayState,
    ProtocolError,
    StateMessage,
    encode_message,
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


def test_incremental_line_reader_frames_only_complete_bounded_records():
    record = encode_message(StateMessage(2, OverlayState.RECORDING)).encode()
    reader = _LineReader()

    assert reader.feed(record[:7]) == []
    assert reader.feed(record[7:]) == [record]
    reader.finish()


def test_incremental_line_reader_rejects_oversize_and_truncated_records():
    reader = _LineReader()
    with pytest.raises(ProtocolError, match="too large"):
        reader.feed(b"x" * MAX_MESSAGE_BYTES)

    reader = _LineReader()
    reader.feed(b'{"v":1')
    with pytest.raises(ProtocolError, match="mid-record"):
        reader.finish()


def test_mailbox_assigns_generations_and_coalesces_pending_states():
    mailbox = OutboundMailbox()

    assert mailbox.publish(OverlayState.RECORDING) == 0
    assert mailbox.publish(OverlayState.MODEL_LOADING) == 1
    assert mailbox.take_nowait() == StateMessage(1, OverlayState.MODEL_LOADING)
    assert mailbox.take_nowait() is None


def test_mailbox_preserves_lifecycle_order_around_latest_state():
    mailbox = OutboundMailbox()
    mailbox.publish(OverlayState.MODEL_LOADING)
    mailbox.lifecycle(LifecycleEvent.MODEL_READY)
    mailbox.publish(OverlayState.TRANSCRIBING)

    assert mailbox.take_nowait() == StateMessage(0, OverlayState.MODEL_LOADING)
    assert mailbox.take_nowait() == LifecycleMessage(1, LifecycleEvent.MODEL_READY)
    assert mailbox.take_nowait() == StateMessage(2, OverlayState.TRANSCRIBING)
    assert mailbox.take_nowait() is None


def test_mailbox_is_bounded_and_keeps_newest_metadata():
    mailbox = OutboundMailbox(capacity=3)
    for state in (
        OverlayState.RECORDING,
        OverlayState.MODEL_LOADING,
        OverlayState.TRANSCRIBING,
        OverlayState.DELIVERING,
    ):
        mailbox.publish(state)
        mailbox.lifecycle(LifecycleEvent.MODEL_READY)

    messages = []
    while (message := mailbox.take_nowait()) is not None:
        messages.append(message)

    assert len(messages) <= 3
    assert messages[-1] == LifecycleMessage(7, LifecycleEvent.MODEL_READY)
    assert all(a.generation < b.generation for a, b in pairwise(messages))


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
