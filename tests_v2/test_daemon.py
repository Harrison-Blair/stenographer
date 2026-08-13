# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic and OS-level tests for daemon.py.

Covered here: the pipeline outcome policy (``classify_pipeline``), the
one-at-a-time admission rule (``can_start``), single-instance-lock mutual
exclusion via a REAL flock on a tmp path, and that ``Daemon.build`` wires all
collaborators lazily (no uinput device, stream, or model opened) with a safe
pre-start ``stop``. Nothing mocks subprocess/UInput/wl-copy/Worker (§6.2); the
real utterance path is the M5 manual dictation acceptance procedure.
"""

from __future__ import annotations

import os

import pytest
from stenographer_v2.daemon import (
    Outcome,
    acquire_single_instance_lock,
    can_start,
    classify_pipeline,
    release_single_instance_lock,
)


def test_gate_failure_is_silent():
    assert classify_pipeline(gate_passed=False, transcript_nonempty=False, deliver_result=None) == (
        Outcome.SILENT,
        None,
    )


def test_empty_transcript_is_silent():
    # Gate passed but the decode was empty/all-gated: success-shaped, no error (§4.7).
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
    # A False deliver on non-empty text is never silent (§4.3): the copy failed,
    # so the chord was withheld and the user must be told.
    assert outcome is Outcome.ERROR
    assert message


def test_can_start_only_when_fully_idle():
    assert can_start(recording=False, busy=False, stopping=False) is True
    assert can_start(recording=True, busy=False, stopping=False) is False
    assert can_start(recording=False, busy=True, stopping=False) is False
    assert can_start(recording=False, busy=False, stopping=True) is False


def test_single_instance_lock_is_mutually_exclusive(tmp_path):
    lock = tmp_path / "stenographer.lock"
    fd = acquire_single_instance_lock(lock)
    assert fd >= 0
    # The PID is recorded in the lock file.
    assert lock.read_text().strip() == str(os.getpid())
    # A second acquire against the SAME path is a distinct open file description,
    # so its non-blocking flock contends even in-process and returns -1.
    assert acquire_single_instance_lock(lock) == -1
    os.close(fd)
    release_single_instance_lock(lock)
    assert not lock.exists()


def test_build_wires_collaborators_lazily():
    # Package A (hotkey.py) is built concurrently against the documented
    # contract; skip this wiring check until it lands, then run it for real.
    pytest.importorskip("stenographer_v2.hotkey")
    from stenographer_v2.config import Config
    from stenographer_v2.daemon import Daemon

    daemon = Daemon.build(Config.defaults())
    try:
        # Built but nothing opened: no stream, no model child, no uinput device.
        assert daemon._recording is False
        assert daemon._busy is False
        assert daemon._listener is not None
        assert daemon._deliverer is not None
        assert daemon._worker.is_alive() is False
        assert daemon._recorder.is_active is False
    finally:
        # stop() before run() must be a safe no-op.
        daemon.stop()
