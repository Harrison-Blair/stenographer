# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon lifecycle behavior and regression coverage."""

from __future__ import annotations

import dataclasses
import threading

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.transcribe.results import TranscriptionResult

from .support import (
    _SPEECH,
    _build_or_skip,
    _current_stamp,
    _daemon,
    _Recorder,
    _run_utterance,
    _summary,
)


def test_build_wires_collaborators_lazily():
    # Package A (hotkey.py) is built concurrently against the documented
    # contract; skip this wiring check until it lands, then run it for real.
    pytest.importorskip("stenographer.lib.hotkey.binding")

    daemon = _build_or_skip(Config.defaults())
    try:
        # Built but nothing opened: startup preparation happens only after the
        # single-instance lock is acquired in run().
        assert daemon._recording is False
        assert daemon._busy is False
        assert daemon._listener is not None
        assert daemon._deliverer is not None
        assert daemon._worker.is_alive() is False
        assert daemon._recorder.is_active is False
        assert daemon._recorder.is_prepared is False
    finally:
        # stop() before run() must be a safe no-op.
        daemon.stop()


def test_build_wires_toggle_mode_press_only():
    # Seen to FAIL against a build that ignores hotkey.mode and wires toggle
    # like hold. Same real-build style as the lazy-wiring test above: nothing
    # is opened, no mocks.
    pytest.importorskip("stenographer.lib.hotkey.binding")

    defaults = Config.defaults()
    hold_cfg = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="hold")
    )
    hold = _build_or_skip(hold_cfg)
    try:
        assert hold._listener._on_start == hold.on_key_down
        assert hold._listener._on_stop == hold.on_key_up
    finally:
        hold.stop()

    toggle_cfg = dataclasses.replace(
        defaults, hotkey=dataclasses.replace(defaults.hotkey, mode="toggle")
    )
    toggle = _build_or_skip(toggle_cfg)
    try:
        # Only presses drive the session; the falling edge must be inert.
        assert toggle._listener._on_start == toggle.on_toggle_press
        assert toggle._listener._on_stop != toggle.on_key_up
        assert toggle._listener._on_stop != toggle.on_key_down
    finally:
        toggle.stop()


def test_a_stale_max_duration_timer_cannot_stop_the_next_utterance():
    # The id doubles as the stale-timer generation. A timer armed for utterance
    # 1 that reaches the lock only after utterance 2 has started must do
    # nothing. Seen to FAIL against ``_on_max_duration`` ignoring its argument.
    result = TranscriptionResult(text="one", duration_seconds=1.0)
    daemon = _daemon(result=result, mode="toggle")
    try:
        _run_utterance(daemon)
        daemon.on_key_down()
        assert daemon._utterance_id == 2
        assert daemon._recording is True

        daemon._on_max_duration(1)
        assert daemon._recording is True

        daemon._on_max_duration(2)
        assert daemon._recording is False
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon.stop()


def test_a_recorder_stop_failure_still_closes_the_utterance(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def stop(self) -> np.ndarray:
            raise OSError("stream vanished")

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = _BrokenRecorder(_SPEECH)
    try:
        daemon.on_key_down()
        daemon.on_key_up()
    finally:
        daemon.stop()

    assert daemon._pipeline_thread is None
    assert "recorder: failed" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)
    assert not [t for t in threading.enumerate() if t.name == "stenographer-pipeline"]


def test_stop_closes_an_in_flight_recording_as_cancelled(daemon_logs):
    # A press then a shutdown must not leave an utterance unaccounted for.
    # Seen to FAIL against a stop() that cleared _recording without taking the
    # record: no pipeline: utterance line was written at all.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon.on_key_down()
    daemon.stop()

    assert "outcome=CANCELLED" in _summary(daemon_logs)
    assert _current_stamp() == ""


def test_a_hybrid_tap_latches_until_the_next_press_whose_release_is_ignored(daemon_logs):
    # Seen to FAIL against a release handler that always stops: the recording
    # was already over before the second press, which then started utt=2. The
    # stopping press's own release must decide nothing — seen to FAIL against a
    # handler without the recording gate, which never logged the ignored line.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="hybrid")
    try:
        daemon.on_toggle_press()
        daemon.on_hybrid_release()
        assert daemon._recording is True

        daemon.on_toggle_press()
        assert daemon._recording is False
        daemon.on_hybrid_release()
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon.stop()

    assert daemon._utterance_id == 1
    line = _summary(daemon_logs)
    assert "mode=hybrid" in line
    assert "outcome=DELIVERED" in line
    assert "hotkey: hybrid_release action=latch" in daemon_logs.text
    assert "hotkey: hybrid_release_ignored reason=not_recording" in daemon_logs.text


def test_a_hybrid_hold_stops_on_release(daemon_logs):
    # Seen to FAIL against a release handler that always latches: the recording
    # survived the release and only stop() closed it, as CANCELLED.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="hybrid")
    try:
        daemon.on_toggle_press()
        daemon._record.started_at -= 1.0
        daemon.on_hybrid_release()
        assert daemon._recording is False
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon.stop()

    assert "outcome=DELIVERED" in _summary(daemon_logs)
    assert "hotkey: hybrid_release action=stop" in daemon_logs.text


def test_only_a_latched_hybrid_recording_arms_the_max_duration_timer():
    # The cap runs from the PRESS in every mode, so the latch arms the timer for
    # what is left of the window. Seen to FAIL against arming at the press, not
    # arming at all, and arming for a flat max_recording_seconds.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="hybrid")
    try:
        daemon.on_toggle_press()
        assert daemon._max_timer is None

        daemon._record.started_at -= 0.3
        daemon.on_hybrid_release()
        assert daemon._recording is True
        assert daemon._max_timer is not None
        assert daemon._max_timer.interval == pytest.approx(
            daemon._cfg.audio.max_recording_seconds - 0.3, abs=0.05
        )

        daemon._on_max_duration(daemon._utterance_id)
        assert daemon._recording is False
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)
    finally:
        daemon.stop()


def test_stop_closes_a_latched_hybrid_recording_as_cancelled(daemon_logs):
    # A latched recording has no key held to end it, so shutdown owes it the one
    # summary line. Seen to FAIL against a stop() that took no record.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="hybrid")
    daemon.on_toggle_press()
    daemon.on_hybrid_release()
    assert daemon._recording is True
    daemon.stop()

    line = _summary(daemon_logs)
    assert "outcome=CANCELLED" in line
    assert "mode=hybrid" in line
    assert _current_stamp() == ""
