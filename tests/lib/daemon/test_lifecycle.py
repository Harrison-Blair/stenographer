# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon lifecycle behavior and regression coverage."""

from __future__ import annotations

import dataclasses
import threading

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.transcribe.errors import WorkerError
from stenographer.lib.transcribe.results import TranscriptionResult

from .support import (
    _SPEECH,
    CANARY,
    _build_or_skip,
    _current_stamp,
    _daemon,
    _daemon_with_status,
    _Listener,
    _Platform,
    _Recorder,
    _run_utterance,
    _Status,
    _summary,
    _Worker,
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


def test_cancel_while_recording_discards_audio_without_starting_pipeline(daemon_logs):
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="never", duration_seconds=1.0)
    )
    try:
        daemon.on_key_down()
        daemon.on_cancel()
        assert status.states == [OverlayState.RECORDING, OverlayState.CANCELLED]
    finally:
        daemon.stop()

    assert daemon._worker.utterances == []
    assert daemon._deliverer.delivered == []
    assert daemon._feedback.cues[-1] == "error"
    assert daemon._notifier.errors == []
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_cancel_during_capture_finalization_never_starts_pipeline(daemon_logs):
    class _CancelingRecorder(_Recorder):
        cancel = None

        def stop(self) -> np.ndarray:
            samples = super().stop()
            assert self.cancel is not None
            self.cancel()
            return samples

    daemon = _daemon(result=TranscriptionResult(text="never", duration_seconds=1.0))
    recorder = _CancelingRecorder(_SPEECH)
    recorder.cancel = daemon.on_cancel
    daemon._recorder = recorder
    try:
        daemon.on_key_down()
        daemon.on_key_up()
    finally:
        daemon.stop()

    assert daemon._pipeline_thread is None
    assert daemon._worker.utterances == []
    assert daemon._deliverer.delivered == []
    assert daemon._feedback.cues == ["record_start", "error"]
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_cancel_while_busy_discards_result_before_delivery(daemon_logs):
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="never", duration_seconds=1.0)
    )
    worker = daemon._worker
    worker.block_transcribe = True
    try:
        daemon.on_key_down()
        daemon.on_key_up()
        assert worker.transcribe_started.wait(timeout=1.0)

        daemon.on_cancel()
        assert status.states[-1] is OverlayState.CANCELLED
        worker.transcribe_release.set()
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=2.0)
        assert not thread.is_alive()
    finally:
        worker.transcribe_release.set()
        daemon.stop()

    assert daemon._deliverer.delivered == []
    assert daemon._notifier.errors == []
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_cancel_while_idle_is_ignored(daemon_logs):
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="never", duration_seconds=1.0)
    )
    try:
        daemon.on_cancel()
    finally:
        daemon.stop()

    assert status.states == []
    assert daemon._feedback.cues == []
    assert "hotkey: cancel_ignored" in daemon_logs.text


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


def test_build_wires_the_worker_callbacks_onto_this_daemon(tmp_path, monkeypatch):
    # The three callbacks are closures over a daemon that does not exist yet
    # when ``Worker`` is constructed. Seen to FAIL against closures bound to a
    # ``daemon`` name captured before assignment (NameError on the first cold
    # load) and against a build that never passed them to the worker at all.
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "config.toml"))
    platform = _Platform()
    status = _Status()
    daemon = Daemon.build(Config.defaults(), clipboard_backend="wl-copy", platform=platform)
    try:
        assert platform.clipboard_backends == ["wl-copy"]
        assert platform.listener is not None
        assert platform.listener.on_cancel == daemon.on_cancel

        daemon._worker._on_model_loading()
        assert status.loading == []
        daemon._status = status

        daemon._worker._on_model_loading()
        assert status.loading == [True]
        daemon._worker._on_model_loading_finished()
        assert status.loading == [True, False]

        daemon._worker._on_transcribing()
        assert status.states == [OverlayState.TRANSCRIBING]
    finally:
        daemon.stop()


def test_model_loading_activity_is_published_and_timed_onto_the_live_record():
    # ``load_ms`` belongs to the utterance the load was started for, and the
    # activity flag must be raised and lowered exactly once around it.
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="one", duration_seconds=1.0), warm=False
    )
    try:
        daemon.on_key_down()
        record = daemon._record
        assert record.load_ms is None

        daemon._on_model_loading()
        assert status.loading == [True]
        assert daemon._model_load_utterance == daemon._utterance_id

        daemon._on_model_loading_finished()
        assert status.loading == [True, False]
        assert record.load_ms is not None
        assert record.load_ms >= 0.0
        assert daemon._model_load_started_at is None
        assert daemon._model_load_utterance is None
    finally:
        daemon.stop()


def test_model_loading_activity_is_suppressed_once_shutdown_began():
    daemon, status = _daemon_with_status()
    try:
        daemon.request_stop()
        daemon._on_model_loading()

        assert status.loading == []
        assert daemon._model_load_started_at is None
    finally:
        daemon.stop()


def test_a_failed_warmup_is_logged_without_the_worker_message(daemon_logs):
    # A ``WorkerError`` round-trips the ASR child's own detail, which can quote
    # decoder text: the warm-up path uses the same safe=False tier as decode.
    class _BrokenWorker(_Worker):
        def warmup(self, utterance: int | None = None) -> None:
            raise WorkerError(f"model load blew up on {CANARY}")

    daemon = _daemon()
    daemon._worker = _BrokenWorker(None, None)
    try:
        daemon._warm_model(1)

        assert "worker: warmup_failed" in daemon_logs.text
        assert "error=WorkerError" in daemon_logs.text
        assert CANARY not in daemon_logs.text
    finally:
        daemon.stop()


def test_a_warmup_failure_during_shutdown_is_not_reported(daemon_logs):
    class _BrokenWorker(_Worker):
        def warmup(self, utterance: int | None = None) -> None:
            raise WorkerError("model load blew up")

    daemon = _daemon()
    daemon._worker = _BrokenWorker(None, None)
    daemon.request_stop()
    try:
        daemon._warm_model(1)
    finally:
        daemon.stop()

    assert "worker: warmup_failed" not in daemon_logs.text


def test_a_press_during_transcription_is_counted_and_refused(daemon_logs):
    # The refused press is the user saying "it is stuck": it must be counted on
    # the utterance that is still running, never start a second one.
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    worker = daemon._worker
    worker.block_transcribe = True
    try:
        daemon.on_key_down()
        daemon.on_key_up()
        assert worker.transcribe_started.wait(timeout=5.0)

        daemon.on_key_down()
        assert daemon._recording is False
        assert daemon._record.ignored_busy_presses == 1
        assert daemon._utterance_id == 1
    finally:
        worker.transcribe_release.set()
        daemon.stop()

    assert "hotkey: key_down_ignored reason=busy" in daemon_logs.text
    assert "pipeline: utterance " in daemon_logs.text


def test_a_second_press_while_recording_is_refused_without_a_count(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    try:
        daemon.on_key_down()
        daemon.on_key_down()

        assert daemon._utterance_id == 1
        assert daemon._record.ignored_busy_presses == 0
    finally:
        daemon.stop()

    assert "hotkey: key_down_ignored reason=recording" in daemon_logs.text


def test_a_recorder_start_failure_closes_the_utterance_and_reports_it(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def __init__(self, samples) -> None:
            super().__init__(samples)
            self.closed = 0

        def start(self) -> None:
            raise OSError("device disappeared")

        def close(self) -> None:
            self.closed += 1

    daemon, status = _daemon_with_status()
    recorder = _BrokenRecorder(_SPEECH)
    daemon._recorder = recorder
    try:
        daemon.on_key_down()

        assert daemon._recording is False
        assert recorder.closed == 1
        assert daemon._notifier.errors == ["could not start recording"]
        assert daemon._feedback.cues == ["error"]
        assert status.states == [OverlayState.ERROR]
    finally:
        daemon.stop()

    assert "recorder: failed" in daemon_logs.text
    assert "phase=start" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


def test_a_release_for_another_generation_or_no_recording_decides_nothing(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    try:
        daemon.on_key_down()
        daemon.on_key_up(generation=99)
        assert daemon._recording is True
        assert daemon._pipeline_thread is None

        daemon.on_key_up()
        thread = daemon._pipeline_thread
        assert thread is not None
        thread.join(timeout=10.0)

        daemon.on_key_up()
        assert daemon._pipeline_thread is thread
    finally:
        daemon.stop()

    assert "hotkey: key_up_ignored reason=not_recording" in daemon_logs.text


def test_a_stale_cancel_cannot_finalize_the_current_recording():
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    try:
        daemon.on_key_down()

        daemon._cancel_recording(99)
        assert daemon._recording is True
        assert daemon._record is not None
    finally:
        daemon.stop()


def test_a_recorder_failure_during_cancel_still_closes_the_utterance(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def stop(self):
            raise OSError("stream vanished")

    daemon, status = _daemon_with_status()
    daemon._recorder = _BrokenRecorder(_SPEECH)
    try:
        daemon.on_key_down()
        daemon.on_cancel()

        assert daemon._recording is False
        assert daemon._busy is False
        assert status.states == [OverlayState.RECORDING, OverlayState.CANCELLED]
    finally:
        daemon.stop()

    assert "recorder: cancel_finalize_failed" in daemon_logs.text
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_a_recorder_failure_during_shutdown_still_closes_the_utterance(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def stop(self):
            raise OSError("stream vanished at teardown")

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = _BrokenRecorder(_SPEECH)
    daemon.on_key_down()
    daemon.stop()

    assert "recorder: cancel_finalize_failed" in daemon_logs.text
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_run_before_build_refuses_rather_than_blocking():
    daemon = _daemon()
    try:
        with pytest.raises(RuntimeError, match=r"daemon\.run\(\) before build\(\)"):
            daemon.run()
    finally:
        daemon.stop()


def test_run_starts_the_listener_and_returns_once_stop_is_requested(daemon_logs):
    daemon = _daemon()
    listener = _Listener(
        chord=frozenset({1}),
        device=None,
        on_start=daemon.on_key_down,
        on_stop=daemon.on_key_up,
        lock=threading.RLock(),
    )
    daemon._listener = listener
    try:
        daemon.request_stop()
        daemon.run()

        assert listener.started.is_set()
        assert daemon._stop_event.is_set()
    finally:
        daemon.stop()

    assert listener.stopped.is_set()
    assert "daemon: running pid=" in daemon_logs.text


def test_a_toggle_press_during_transcription_is_counted_and_refused(daemon_logs):
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="toggle")
    worker = daemon._worker
    worker.block_transcribe = True
    try:
        daemon.on_toggle_press()
        daemon.on_toggle_press()
        assert worker.transcribe_started.wait(timeout=5.0)

        daemon.on_toggle_press()
        assert daemon._record.ignored_busy_presses == 1
        assert daemon._utterance_id == 1
        assert daemon._recording is False
    finally:
        worker.transcribe_release.set()
        daemon.stop()

    assert "hotkey: key_down_ignored" not in daemon_logs.text
    assert "pipeline: utterance utt=1 " in daemon_logs.text


def test_shutdown_during_capture_finalization_takes_the_pill_straight_down(daemon_logs):
    # Cancelling because the daemon is stopping must leave HIDDEN behind, not
    # the CANCELLED pill a user-requested cancel shows.
    daemon, status = _daemon_with_status(
        result=TranscriptionResult(text="never", duration_seconds=1.0)
    )
    try:
        daemon.on_key_down()
        daemon.request_stop()
        daemon.on_key_up()

        assert daemon._pipeline_thread is None
        assert daemon._busy is False
        assert status.states == [OverlayState.RECORDING, OverlayState.HIDDEN]
        assert daemon._worker.utterances == []
    finally:
        daemon.stop()

    assert "outcome=CANCELLED" in _summary(daemon_logs)
