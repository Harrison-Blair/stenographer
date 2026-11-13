# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon lifecycle behavior and regression coverage."""

from __future__ import annotations

import dataclasses
import json
import threading
import time

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.contracts.loading_model import LoadingModel
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.refine.cancellation import never_cancelled
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
    _no_network_cfg,
    _Platform,
    _Recorder,
    _run_utterance,
    _Status,
    _summary,
    _TrackerPlatform,
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
        assert daemon._worker.process_ids == ()
        assert not daemon._recorder.capturing
    finally:
        # stop() before run() must be a safe no-op.
        daemon.stop()


@pytest.mark.parametrize("field", ["binding", "general_binding", "cancel_binding"])
def test_build_identifies_invalid_binding_setting(field):
    from stenographer.lib.hotkey.errors import BindingError

    cfg = _no_network_cfg()
    cfg = dataclasses.replace(cfg, hotkey=dataclasses.replace(cfg.hotkey, **{field: "KEY_NOPE"}))
    with pytest.raises(BindingError, match=rf"hotkey\.{field}: unknown key 'KEY_NOPE'"):
        Daemon.build(cfg, clipboard_backend="wl-copy", platform=_Platform())


def test_a_busy_press_of_the_other_binding_holds_the_paste_until_released():
    # Hybrid default: Agent = Right Ctrl, General = Right Alt. After a stop the
    # pipeline is busy; holding Right Alt then is refused by the daemon, and a
    # paste now would send Alt+Ctrl+V. The daemon's own deliverer must wait on
    # the real tracker it was wired to. Busy stands in for transcription so
    # nothing records.
    platform = _TrackerPlatform()
    daemon = Daemon.build(_no_network_cfg(), clipboard_backend="wl-copy", platform=platform)
    try:
        tracker = platform.listener
        (general_key,) = tracker._bindings["general"]
        daemon._busy = True
        tracker._key_event(1, general_key, 1)
        assert daemon._recording is False

        delivery = threading.Thread(target=daemon._deliverer.deliver, args=("x",))
        delivery.start()
        delivery.join(timeout=0.1)
        assert delivery.is_alive()
        assert platform.injector.chords == 0

        tracker._key_event(1, general_key, 0)
        delivery.join(timeout=1.0)
        assert not delivery.is_alive()
        assert platform.injector.chords == 1
    finally:
        daemon.stop()


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
        _join_pipeline(daemon)
    finally:
        daemon.stop()

    assert daemon._worker.utterances == []
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
        _join_pipeline(daemon)
    finally:
        daemon.stop()

    assert daemon._worker.utterances == []
    assert daemon._deliverer.delivered == []
    assert daemon._feedback.cues == ["record_start", "error"]
    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_cancel_during_finalization_after_a_delivered_utterance_still_cancels(daemon_logs):
    class _CancelingRecorder(_Recorder):
        cancel = None

        def stop(self) -> np.ndarray:
            samples = super().stop()
            if self.cancel is not None:
                self.cancel()
            return samples

    daemon = _daemon(result=TranscriptionResult(text="one two", duration_seconds=1.0))
    recorder = _CancelingRecorder(_SPEECH)
    daemon._recorder = recorder
    try:
        daemon.on_key_down()
        daemon.on_key_up()
        first_pipeline = daemon._pipeline_thread
        first_pipeline.join(timeout=2.0)
        assert not first_pipeline.is_alive()
        assert len(daemon._deliverer.delivered) == 1

        recorder.cancel = daemon.on_cancel
        daemon.on_key_down()
        daemon.on_key_up()
        _join_pipeline(daemon)
    finally:
        daemon.stop()

    assert len(daemon._worker.utterances) == 1
    assert len(daemon._deliverer.delivered) == 1
    assert "outcome=CANCELLED" in daemon_logs.text


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
    # arming at all, and arming for a flat 600 seconds (the fixed cap).
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0), mode="hybrid")
    try:
        daemon.on_toggle_press()
        assert daemon._max_timer is None

        daemon._record.started_at -= 0.3
        daemon.on_hybrid_release()
        assert daemon._recording is True
        assert daemon._max_timer is not None
        assert daemon._max_timer.interval == pytest.approx(600 - 0.3, abs=0.05)

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
    # The two callbacks are closures over a daemon that does not exist yet
    # when ``Worker`` is constructed. Seen to FAIL against closures bound to a
    # ``daemon`` name captured before assignment (NameError on the first cold
    # load) and against a build that never passed them to the worker at all.
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(tmp_path / "config.toml"))
    platform = _Platform()
    status = _Status()
    # `_no_network_cfg`: this builds via `Daemon.build` directly (to inject the
    # fake `platform`), not through `_build_or_skip`, so it needs the same
    # off-the-network config for itself — see `_no_network_cfg`'s docstring.
    daemon = Daemon.build(_no_network_cfg(), clipboard_backend="wl-copy", platform=platform)
    try:
        assert platform.clipboard_backends == ["wl-copy"]
        assert platform.listener is not None
        assert platform.listener.on_cancel == daemon.on_cancel

        daemon._worker._on_model_loading()
        assert status.loading == []
        daemon._status = status

        daemon._worker._on_model_loading()
        assert status.loading == [(LoadingModel.ASR, True)]
        daemon._worker._on_model_loading_finished()
        assert status.loading == [(LoadingModel.ASR, True), (LoadingModel.ASR, False)]
    finally:
        daemon.stop()


def test_cancel_while_worker_waits_for_model_lock_keeps_cancelled_state():
    from tests.lib.transcribe.support import FakeAsrTransport

    platform = _Platform()
    platform.asr_transport = lambda: FakeAsrTransport()
    status = _Status()
    daemon = Daemon.build(_no_network_cfg(), clipboard_backend="wl-copy", platform=platform)
    daemon._status = status
    started = threading.Event()

    def transcribe():
        started.set()
        daemon._worker.transcribe(_SPEECH, 1)

    try:
        daemon._busy = True
        daemon._utterance_id = 1
        daemon._publish_state(OverlayState.TRANSCRIBING)
        with daemon._worker._lock:
            thread = threading.Thread(target=transcribe)
            thread.start()
            assert started.wait(1)
            daemon.on_cancel()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert status.states == [OverlayState.TRANSCRIBING, OverlayState.CANCELLED]
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
        assert status.loading == [(LoadingModel.ASR, True)]
        assert daemon._model_load_utterance == daemon._utterance_id

        daemon._on_model_loading_finished()
        assert status.loading == [(LoadingModel.ASR, True), (LoadingModel.ASR, False)]
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


def test_refine_loading_activity_counts_open_loads():
    # Two concurrent openers (the refine warm thread and the pipeline thread)
    # must not raise the pill twice or drop it before the last one is done.
    daemon, status = _daemon_with_status()
    try:
        daemon._on_refine_loading()
        daemon._on_refine_loading()
        assert status.loading == [(LoadingModel.REFINE, True)]

        daemon._on_refine_loading_finished()
        assert status.loading == [(LoadingModel.REFINE, True)]

        daemon._on_refine_loading_finished()
        assert status.loading == [(LoadingModel.REFINE, True), (LoadingModel.REFINE, False)]
    finally:
        daemon.stop()


def test_refine_loading_start_is_suppressed_once_shutdown_began_but_the_finish_still_clears():
    daemon, status = _daemon_with_status()
    try:
        daemon.request_stop()
        daemon._on_refine_loading()
        assert status.loading == []

        daemon._on_refine_loading_finished()
        assert status.loading == [(LoadingModel.REFINE, False)]
    finally:
        daemon.stop()


def test_refine_loading_publish_happens_while_the_open_load_counter_is_locked():
    # A publish issued after `_refine_load_lock` is released can interleave
    # with a concurrent opener/closer and get reordered on the wire (an
    # opener's True landing after a closer's False for the same edge count).
    # Publishing while still holding the lock is what makes the edge and its
    # announcement atomic with respect to the counter.
    daemon, _ = _daemon_with_status()
    seen_locked: list[bool] = []

    class _LockCheckingStatus:
        def publish(self, state, profile=None):
            return 0

        def loading_activity(self, model, active):
            seen_locked.append(daemon._refine_load_lock.locked())

        def audio_block(self, samples, sample_rate, stream_epoch):
            pass

        def close(self):
            pass

    daemon._status = _LockCheckingStatus()
    try:
        daemon._on_refine_loading()
        daemon._on_refine_loading_finished()
    finally:
        daemon.stop()

    assert seen_locked == [True, True]


def test_the_built_daemon_hands_its_refine_observers_to_the_refiner(monkeypatch):
    captured: dict = {}

    def fake_build_refiner(cfg, **kwargs):
        captured.update(kwargs)
        return None

    # Patched before construction: `_daemon()` builds `Daemon(...)` directly,
    # which calls `build_refiner` from inside `__init__`.
    monkeypatch.setattr("stenographer.lib.daemon.daemon.build_refiner", fake_build_refiner)

    daemon = _daemon()
    try:
        assert captured["on_model_loading"] == daemon._on_refine_loading
        assert captured["on_model_loading_finished"] == daemon._on_refine_loading_finished
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
        def start(self, on_failure=None) -> None:
            raise OSError("device disappeared")

    daemon, status = _daemon_with_status()
    recorder = _BrokenRecorder(_SPEECH)
    daemon._recorder = recorder
    try:
        daemon.on_key_down()

        assert daemon._recording is False
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


def test_cancel_abandons_the_capture_without_waiting_for_its_end(daemon_logs):
    class _BrokenRecorder(_Recorder):
        def stop(self):
            raise AssertionError("cancel waited for the capture to end")

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


def test_run_starts_the_listener_and_returns_once_stop_is_requested(daemon_logs):
    daemon = _daemon()
    listener = _Listener(
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
        _join_pipeline(daemon)

        assert daemon._busy is False
        assert status.states == [OverlayState.RECORDING, OverlayState.HIDDEN]
        assert daemon._worker.utterances == []
    finally:
        daemon.stop()

    assert "outcome=CANCELLED" in _summary(daemon_logs)


def test_stop_waits_for_an_in_flight_refine_before_unloading_the_model():
    # Seen to FAIL when unload() ran before the pipeline thread (which can
    # still be inside refine()) was joined: an in-flight request can
    # re-establish Ollama's ``keep_alive`` after the model was told to
    # unload, pinning it in VRAM. Asserted on ORDER, not timing: the fake
    # refiner blocks in refine() on ``hold_refine`` (bounded by its own
    # timeout, so a bug can never hang the test), and unload() records
    # whether the pipeline thread was still alive at the moment it ran — a
    # direct, non-racy check of what actually happened, not of scheduling
    # luck.
    order: list[str] = []
    pipeline_alive_at_unload: list[bool] = []
    refine_entered = threading.Event()
    unload_entered = threading.Event()
    hold_refine = threading.Event()
    daemon_holder: list[Daemon] = []

    class _BlockingRefiner:
        def will_refine(self, text: str) -> bool:
            return True

        @property
        def last_result(self):
            return None

        def refine(self, text: str, *, profile, cancelled=never_cancelled) -> str:
            order.append("refine")
            refine_entered.set()
            hold_refine.wait(timeout=5.0)
            return text

        def unload(self) -> None:
            thread = daemon_holder[0]._pipeline_thread
            pipeline_alive_at_unload.append(thread.is_alive() if thread is not None else False)
            order.append("unload")
            unload_entered.set()

    daemon = _daemon(
        result=TranscriptionResult(text="one", duration_seconds=1.0),
        refiner=_BlockingRefiner(),
    )
    daemon_holder.append(daemon)
    stop_errors: list[BaseException] = []

    def _run_stop() -> None:
        try:
            daemon.stop()
        except BaseException as exc:  # surfaced via the assertion below, not swallowed
            stop_errors.append(exc)

    try:
        daemon.on_key_down()
        daemon.on_key_up()
        assert refine_entered.wait(timeout=5.0)

        stop_thread = threading.Thread(target=_run_stop, name="test-stop")
        stop_thread.start()

        # THIS WAIT IS THE DETECTION MECHANISM, not a courtesy — do not shorten
        # or remove it. The passing direction needs no timing at all: unload()
        # cannot run until hold_refine is released below, full stop. But the
        # only way to observe a *buggy* stop() reaching unload() early is to
        # give it a window to do so before we ourselves release hold_refine;
        # without one, releasing immediately could let the pipeline finish
        # before a slow-to-schedule buggy stop() even gets there, and
        # unload()'s own is_alive() check would then read False — a false
        # pass against the very bug this test exists to catch. A buggy
        # stop() reaches unload() in a handful of Python statements with no
        # blocking calls in between, so 1 second is generous; this has been
        # verified to hold under heavy contention (48 spinners on 16 cores).
        unload_entered.wait(timeout=1.0)
        hold_refine.set()
        stop_thread.join(timeout=10.0)
        assert not stop_thread.is_alive()
    finally:
        hold_refine.set()

    assert stop_errors == []
    assert order == ["refine", "unload"]
    assert pipeline_alive_at_unload == [False]


def test_stop_does_not_wait_out_a_hung_refine_warmup():
    # Seen to FAIL when the refine warm-up join drew on the full shared
    # shutdown budget (_STOP_BUDGET_SECONDS, 30s) instead of its own small
    # cap (_REFINE_WARMUP_JOIN_SECONDS, 1s): stop() would then take the whole
    # 30s waiting out a warm-up that never finishes, making Ctrl-C look hung
    # against a cold or unreachable Ollama. That join no longer buys
    # correctness now that the refiner's own unload() guarantees residency
    # regardless (see _release_refine_model's docstring), so there is nothing
    # left to justify the long wait. Bounded well under both the 30s shared
    # budget and the warm-up thread's own 10s safety valve, so a regression
    # back to the shared deadline fails fast rather than hanging the test.
    warm_entered = threading.Event()
    release_warm = threading.Event()

    class _HungWarmupRefiner:
        def warm(self) -> None:
            warm_entered.set()
            release_warm.wait(timeout=10.0)

        def unload(self) -> None:
            pass

    daemon = _daemon(refiner=_HungWarmupRefiner())
    daemon._start_refine_warmup()
    try:
        assert warm_entered.wait(timeout=5.0)

        started_at = time.perf_counter()
        daemon.stop()
        elapsed = time.perf_counter() - started_at

        assert elapsed < 5.0, elapsed
    finally:
        release_warm.set()


def test_stop_bounds_the_total_wait_when_every_shutdown_join_is_wedged(monkeypatch):
    """Pins the aggregate shutdown ceiling as an executable claim.

    Wedges all three of stop()'s bounded waits at once — a hung ASR warm-up
    thread, a wedged pipeline thread, and a hung refine warm-up — with
    ``_STOP_BUDGET_SECONDS`` monkeypatched small so the test stays fast. The
    ASR warm-up's fake ``shutdown()`` is a no-op (it does not release the
    thread), so this does not lean on ``Worker._lock`` the way production
    does: it proves the shared deadline itself bounds a hung ASR warm-up,
    which is the gap a correct worst-case analysis could otherwise hide
    behind a dependency living outside this file.

    The bound is ``1.5 * _STOP_BUDGET_SECONDS`` rather than
    ``_STOP_BUDGET_SECONDS + _REFINE_WARMUP_JOIN_SECONDS``: with every wait
    wedged, the ASR-warmup join (first in line) always exhausts the whole
    shared deadline, so the refine warm-up join's own cap never has anything
    left to spend regardless of its value — a full extra
    ``_REFINE_WARMUP_JOIN_SECONDS`` of slack would be wide enough to let a
    regression that gives the ASR-warmup and pipeline joins a full fresh
    budget EACH (2x the shared deadline, instead of sharing it) pass
    unnoticed. ``1.5x`` sits with equal margin between the correct total
    (~1x, confirmed empirically) and that regression's total (~2x).

    Does NOT independently catch a reverted ``min()`` in
    ``_release_refine_model`` (structurally cannot: the shared deadline is
    already spent by the time the refine warm-up join runs, so wrapping it in
    ``min()`` or not makes no observable difference here) — that regression
    is what ``test_stop_does_not_wait_out_a_hung_refine_warmup`` above pins,
    by wedging *only* the refine warm-up so the shared budget is still there
    to be misspent.
    """
    import stenographer.lib.daemon.daemon as daemon_module

    patched_budget = 0.8
    monkeypatch.setattr(daemon_module, "_STOP_BUDGET_SECONDS", patched_budget)

    warmup_release = threading.Event()
    refine_warm_release = threading.Event()

    class _WedgedWorker(_Worker):
        def warmup(self, utterance: int | None = None) -> None:
            warmup_release.wait(timeout=10.0)

        def shutdown(self) -> None:
            # Deliberately does NOT release warmup_release: this test must
            # not depend on the real Worker._lock coupling that daemon.py's
            # own comment documents as making the ASR-warmup join cheap in
            # production.
            pass

    class _WedgedRefiner:
        def warm(self) -> None:
            refine_warm_release.wait(timeout=10.0)

        def unload(self) -> None:
            pass

    daemon = _daemon(
        result=TranscriptionResult(text="one", duration_seconds=1.0),
        refiner=_WedgedRefiner(),
    )
    worker = _WedgedWorker(daemon._worker._result, daemon._worker._error)
    worker.block_transcribe = True
    daemon._worker = worker
    daemon._pipeline._worker = worker

    try:
        daemon.on_key_down()
        daemon.on_key_up()
        assert worker.transcribe_started.wait(timeout=5.0)
        daemon._start_refine_warmup()

        started_at = time.perf_counter()
        daemon.stop()
        elapsed = time.perf_counter() - started_at

        assert elapsed < 1.5 * patched_budget, elapsed
    finally:
        warmup_release.set()
        worker.transcribe_release.set()
        refine_warm_release.set()


def test_the_daemon_refine_request_carries_the_vocabulary(ollama_wire, monkeypatch):
    from stenographer.lib.refine import factory

    from .support import _Deliverer, _Feedback, _Listener, _Notifier, _Recorder, _Worker

    monkeypatch.setattr(factory, "MIN_WORDS", 1)
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        refine=dataclasses.replace(
            defaults.refine, enabled=True, vocabulary=("Kubernetes", "PipeWire")
        ),
    )
    daemon = Daemon(
        cfg=cfg,
        feedback=_Feedback(),
        notifier=_Notifier(),
        worker=_Worker(None, None),
        recorder=_Recorder(np.zeros(16000, dtype=np.float32)),
    )
    daemon._listener = _Listener(lock=threading.RLock())
    daemon._deliverer = _Deliverer()
    try:
        daemon._refiner.refine("alpha bravo charlie")
    finally:
        daemon.stop()

    assert len(ollama_wire) == 1
    wire = json.dumps(ollama_wire[0]["messages"])
    assert "Kubernetes" in wire
    assert "PipeWire" in wire


def test_a_capture_that_stops_during_a_dictation_ends_it_with_the_microphone_error(daemon_logs):
    from stenographer.lib.audio.recorder import Recorder
    from stenographer.lib.platform.errors import MicCaptureError

    from .support import _MicCapture

    capture = _MicCapture()
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = Recorder(capture_factory=lambda: capture, device=None, max_seconds=10)
    try:
        daemon.on_key_down()
        assert daemon._recording is True
        capture.on_block(np.zeros(512, dtype=np.float32))

        capture.on_block(MicCaptureError("pw-record exited unexpectedly with status 1"))

        deadline = time.monotonic() + 2
        while daemon._recording or daemon._busy:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not capture.running
        assert daemon._notifier.errors == ["recording failed; audio was discarded"]
        # The key release that follows changes nothing.
        daemon.on_key_up()
    finally:
        daemon.stop()

    assert daemon._worker.utterances == []
    assert "recorder: failed" in daemon_logs.text
    assert "outcome=ERROR" in _summary(daemon_logs)


class _SlowStopCapture:
    """A ``MicCapture`` whose ``stop`` blocks the way ending a real child does."""

    def __init__(self) -> None:
        from stenographer.lib.platform.errors import MicCaptureError

        self._error = MicCaptureError
        self.running = False
        self.stopping = threading.Event()
        self.release = threading.Event()

    def start(self, target, on_block) -> None:
        if self.running:
            raise self._error("microphone capture is already running")
        self.running = True

    def stop(self) -> None:
        self.stopping.set()
        self.release.wait(5)
        self.running = False


def test_a_press_at_once_after_a_cancel_starts_while_the_old_capture_still_ends(daemon_logs):
    from stenographer.lib.audio.recorder import Recorder

    made: list[_SlowStopCapture] = []

    def factory():
        made.append(_SlowStopCapture())
        return made[-1]

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = Recorder(capture_factory=factory, device=None, max_seconds=60)
    try:
        daemon.on_key_down()
        daemon.on_cancel()

        press = threading.Thread(target=daemon.on_key_down)
        press.start()
        press.join(1)

        # The old capture is still ending; the press did not wait for it.
        assert not press.is_alive()
        assert made[0].running
        assert daemon._notifier.errors == []
        assert daemon._recording is True
        assert daemon._utterance_id == 2
        assert made[1].running
    finally:
        for capture in made:
            capture.release.set()
        daemon.stop()

    assert "recorder: failed" not in daemon_logs.text
    assert not any(capture.running for capture in made)


def test_a_press_and_release_during_a_failed_captures_end_start_nothing(daemon_logs):
    # Through the real listener dispatch: a press while the daemon is busy is
    # ignored at once, so the release behind it is never queued behind a wait.
    from stenographer.lib.audio.recorder import Recorder
    from stenographer.lib.hotkey.chord_tracker import ChordTracker
    from stenographer.lib.platform.errors import MicCaptureError

    capture = _SlowStopCapture()
    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = Recorder(capture_factory=lambda: capture, device=None, max_seconds=60)
    tracker = ChordTracker(
        lock=threading.RLock(),
        bindings={"agent": frozenset({1})},
        on_binding_start=lambda _name: daemon.on_key_down(),
        on_binding_stop=lambda _name: daemon.on_key_up(),
    )
    tracker._held_by_device[1] = set()
    try:
        daemon.on_key_down()
        daemon._recorder._take.receive(MicCaptureError("pw-record exited"))
        assert capture.stopping.wait(2)

        press = threading.Thread(target=lambda: tracker._key_event(1, 1, 1))
        press.start()
        press.join(1)
        release = threading.Thread(target=lambda: tracker._key_event(1, 1, 0))
        release.start()
        release.join(1)

        assert not press.is_alive()
        assert not release.is_alive()
        capture.release.set()
        deadline = time.monotonic() + 5
        while daemon._busy:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert daemon._utterance_id == 1
        assert daemon._recording is False
        assert daemon._notifier.errors == ["recording failed; audio was discarded"]
    finally:
        capture.release.set()
        daemon.stop()

    assert "hotkey: key_down_ignored reason=busy" in daemon_logs.text


def _join_pipeline(daemon: Daemon) -> None:
    thread = daemon._pipeline_thread
    if thread is not None:
        thread.join(timeout=10.0)
        assert not thread.is_alive()


_FAKE_PW_RECORD = """#!{python}
import os
import struct
import sys
import time
from pathlib import Path

folder = Path(os.environ["PW_FAKE_DIR"])
sys.stdout.buffer.write(struct.pack("<512f", *([0.0] * 512)))
sys.stdout.buffer.flush()
fail = folder / "fail-next"
if fail.exists():
    fail.unlink()
    raise SystemExit(1)
while True:
    time.sleep(0.05)
"""


def test_no_capture_child_outlives_cancels_a_failure_and_the_daemon_stop(
    tmp_path, monkeypatch, daemon_logs
):
    import os
    import sys

    from stenographer.lib.audio.recorder import Recorder
    from stenographer.lib.platform.linux.mic_capture import LinuxMicCapture

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pw-record"
    fake.write_text(_FAKE_PW_RECORD.format(python=sys.executable))
    fake.chmod(0o755)
    children = tmp_path / "children"
    children.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PW_FAKE_DIR", str(children))

    pids: list[int] = []

    class CountingCapture(LinuxMicCapture):
        def start(self, target, on_block):
            super().start(target, on_block)
            pids.append(self._process.pid)

    def alive() -> list[int]:
        living = []
        for pid in pids:
            try:
                os.kill(pid, 0)  # an unreaped child (zombie) also counts
            except ProcessLookupError:
                continue
            living.append(pid)
        return living

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = Recorder(capture_factory=CountingCapture, device=None, max_seconds=60)
    try:
        for _ in range(4):  # quick cancel-and-press
            daemon.on_key_down()
            daemon.on_cancel()
        (children / "fail-next").write_text("")
        daemon.on_key_down()
        deadline = time.monotonic() + 5
        while daemon._recording or daemon._busy:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert daemon._notifier.errors == ["recording failed; audio was discarded"]
        daemon.on_key_down()
        assert daemon._recording is True
    finally:
        daemon.stop()

    assert len(pids) == 6
    assert alive() == []


def test_a_release_ends_its_capture_before_it_returns_and_keeps_later_audio_out():
    # Speech after the release must not enter the dictation, and the
    # microphone is closed when the release returns.
    from stenographer.lib.audio.recorder import Recorder

    from .support import _MicCapture

    class RecordingThreadCapture(_MicCapture):
        def stop(self) -> None:
            self.stopped_on = threading.current_thread()
            super().stop()

    capture = RecordingThreadCapture()
    daemon = _daemon()
    daemon._recorder = Recorder(capture_factory=lambda: capture, device=None, max_seconds=60)
    gate = threading.Event()
    observed: list[np.ndarray] = []

    def held_pipeline(samples: np.ndarray) -> None:
        gate.wait(5)
        observed.append(samples.copy())

    daemon._run_pipeline = held_pipeline
    try:
        daemon.on_key_down()
        capture.on_block(np.zeros(512, dtype=np.float32))
        daemon.on_key_up()

        # Ended on the release path itself, not later on another thread.
        assert capture.stopped_on is threading.current_thread()
        assert not capture.running
        capture.on_block(np.ones(512, dtype=np.float32))
        daemon.on_key_down()
        assert daemon._utterance_id == 1  # a press while busy is ignored
        gate.set()
        _join_pipeline(daemon)
    finally:
        gate.set()
        daemon.stop()

    assert len(observed) == 1
    assert observed[0].size == 512
    assert float(observed[0].sum()) == 0.0


def test_a_capture_that_fails_before_its_start_returns_ends_the_dictation(daemon_logs):
    # The reader can report an immediate child exit while on_key_down still
    # holds the state lock; the dictation must still end with the error.
    from stenographer.lib.audio.recorder import Recorder
    from stenographer.lib.platform.errors import MicCaptureError

    from .support import _MicCapture

    class FailsAtOnce(_MicCapture):
        def start(self, target, on_block) -> None:
            super().start(target, on_block)
            on_block(MicCaptureError("pw-record exited unexpectedly with status 1"))

    daemon = _daemon(result=TranscriptionResult(text="one", duration_seconds=1.0))
    daemon._recorder = Recorder(capture_factory=FailsAtOnce, device=None, max_seconds=60)
    try:
        daemon.on_key_down()
        deadline = time.monotonic() + 5
        while daemon._recording or daemon._busy:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert daemon._notifier.errors == ["recording failed; audio was discarded"]
        daemon.on_key_down()
        assert daemon._recording is True  # the next press starts normally
    finally:
        daemon.stop()

    assert daemon._worker.utterances == []
    assert "recorder: failed phase=stop" in daemon_logs.text
