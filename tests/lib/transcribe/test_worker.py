# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the worker protocol, lifecycle, and timeout policies.

No process spawn, no Model, no network. The real lifecycle (spawn, decode
through the child, idle-kill, restart-if-dead) is covered by the integration
smoke suite in test_worker_smoke.py.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.transcribe import worker as worker_module
from stenographer.lib.transcribe.errors import (
    PathologicalOutputError,
    WorkerCrashedError,
    WorkerError,
    WorkerModelError,
    WorkerPathologicalError,
    WorkerTimeoutError,
)
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker import Worker
from stenographer.lib.transcribe.worker_policy import (
    classify_error,
    decode_timeout_seconds,
    error_is_safe_to_render,
    interpret_response,
    should_arm_idle_timer,
)
from tests.lib.transcribe.support import FakeAsrProcess, FakeAsrTransport, _reply_normally

_WORKER_LOGGER = "stenographer.lib.transcribe.worker"


def test_interpret_response_returns_ok_result():
    result = TranscriptionResult(text="hi", duration_seconds=1.0, segments=[])
    assert interpret_response(("ok", result)) is result


def test_interpret_response_returns_nothing_for_the_model_ready_reply():
    assert interpret_response(("model_ready",)) is None


def test_interpret_response_pathological_raises():
    with pytest.raises(WorkerPathologicalError) as exc:
        interpret_response(("error", "pathological", "decoder word density exceeded"))
    assert str(exc.value) == "decoder word density exceeded"


def test_interpret_response_inference_raises():
    with pytest.raises(WorkerError) as exc:
        interpret_response(("error", "inference", "RuntimeError: boom"))
    # An inference error is a plain WorkerError, not the pathological subclass.
    assert not isinstance(exc.value, WorkerPathologicalError)
    assert str(exc.value) == "RuntimeError: boom"


def test_an_unknown_response_tag_raises_without_echoing_the_message():
    secret = "the dictated transcript text"
    with pytest.raises(WorkerError) as exc:
        interpret_response(("bogus", secret))
    assert secret not in str(exc.value)


def test_decode_timeout_has_sixty_second_floor():
    assert decode_timeout_seconds(0) == 60.0
    assert decode_timeout_seconds(16_000 * 10) == 60.0
    assert decode_timeout_seconds(16_000 * 15) == 60.0


def test_decode_timeout_is_four_times_actual_audio_duration():
    assert decode_timeout_seconds(16_000 * 20) == 80.0
    assert decode_timeout_seconds(16_000 * 125) == 500.0


def test_should_arm_idle_timer_when_idle_and_unheld():
    assert (
        should_arm_idle_timer(
            idle_seconds=60.0,
            hold_active=False,
            shutdown_requested=False,
            process_alive=True,
        )
        is True
    )


@pytest.mark.parametrize(
    "override",
    [
        {"idle_seconds": 0.0},
        {"hold_active": True},
        {"shutdown_requested": True},
        {"process_alive": False},
    ],
)
def test_should_arm_idle_timer_each_gate_blocks(override):
    kwargs = {
        "idle_seconds": 60.0,
        "hold_active": False,
        "shutdown_requested": False,
        "process_alive": True,
    }
    kwargs.update(override)
    assert should_arm_idle_timer(**kwargs) is False


def test_only_the_pathological_decode_failure_may_render_its_own_message():
    """The child's log tier, as the pure decision the child loop asks for.

    Seen to FAIL against ``safe=False`` for every decode failure, which threw
    away the counts-only rejection reason that is the sole account of a
    discarded decode — and against ``safe=True`` for every one, which would let
    the inference stack quote audio-derived text into the log.
    """
    assert error_is_safe_to_render(PathologicalOutputError("word density 312 > 40")) is True
    assert error_is_safe_to_render(RuntimeError("decoded: hello there")) is False
    assert error_is_safe_to_render(ValueError("cannot reshape")) is False


def test_classify_error_pathological():
    assert classify_error(PathologicalOutputError("invalid decoder timestamp")) == (
        "pathological",
        "invalid decoder timestamp",
    )


def test_classify_error_inference():
    assert classify_error(ValueError("bad input")) == ("inference", "ValueError: bad input")


def test_classify_error_detail_is_leak_free():
    # A leaked transcript would only reach classify_error via the exception's
    # own message; the helper must not append samples or transcript of its own.
    transcript = "please do not leak this dictated sentence"
    kind, detail = classify_error(RuntimeError("decode failed"))
    assert kind == "inference"
    assert transcript not in detail
    assert detail == "RuntimeError: decode failed"


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("WorkerPathologicalError", "pathological"),
        ("WorkerTimeoutError", "timeout"),
        ("WorkerCrashedError", "crashed"),
        ("WorkerModelError", "model_failed"),
        ("WorkerError", "decode_failed"),
    ],
)
def test_failure_measurement_classification(kind, expected):
    from stenographer.lib.transcribe import errors
    from stenographer.lib.transcribe.worker_policy import classify_worker_failure

    assert classify_worker_failure(getattr(errors, kind)("private")) == expected


@pytest.fixture
def make_worker():
    """Build workers over a fake transport and shut each one down after the test."""
    workers: list[Worker] = []

    def make(transport, *, idle_seconds: float = 0.0, **observers) -> Worker:
        cfg = replace(Config.loads("").asr, idle_unload_seconds=idle_seconds)
        worker = Worker(cfg, transport=transport, **observers)
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.shutdown()


def _child_running(worker: Worker) -> bool:
    process = worker._process
    return process is not None and process.is_running()


def _observed() -> tuple[list[str], dict]:
    events: list[str] = []
    observers = {
        name: (lambda event=event: events.append(event))
        for name, event in (
            ("on_model_loading", "model_loading"),
            ("on_model_loading_finished", "model_loading_finished"),
        )
    }
    return events, observers


def test_warmup_loads_the_model_and_announces_the_lifecycle_in_order(make_worker):
    events, observers = _observed()
    transport = FakeAsrTransport()

    worker = make_worker(transport, **observers)
    worker.warmup(7)

    assert transport.spawned[0].sent == [("load", 7)]
    assert events == ["model_loading", "model_loading_finished"]
    assert worker.is_model_ready is True
    assert _child_running(worker) is True
    assert worker.process_ids == (4321,)


def test_a_second_warmup_reuses_the_already_loaded_model(make_worker):
    events, observers = _observed()
    transport = FakeAsrTransport()

    worker = make_worker(transport, **observers)
    worker.warmup()
    worker.warmup()

    assert transport.spawned[0].sent == [("load", None)]
    assert events == ["model_loading", "model_loading_finished"]
    assert len(transport.spawned) == 1


def test_a_cold_transcription_loads_then_decodes_and_measures_both(make_worker):
    events, observers = _observed()
    transport = FakeAsrTransport()

    worker = make_worker(transport, **observers)
    result = worker.transcribe(np.zeros(16000, dtype=np.float32), 5)

    child = transport.spawned[0]
    assert [message[0] for message in child.sent] == ["load", "job"]
    assert child.sent[1][2] == 5
    assert result.text == "hello there"
    assert events == [
        "model_loading",
        "model_loading_finished",
    ]
    timings = worker.last_timings
    assert timings is not None
    assert timings.load_ms is not None
    # decode_ms is the child's own inference measurement, not a round trip.
    assert timings.decode_ms == 12.5
    assert timings.round_trip_ms is not None
    assert timings.lock_wait_ms >= 0.0


def test_a_warm_transcription_reports_no_load_of_its_own(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport)
    worker.warmup()
    worker.transcribe(np.zeros(16000, dtype=np.float32))

    assert [message[0] for message in transport.spawned[0].sent] == ["load", "job"]
    assert worker.last_timings.load_ms is None
    assert worker.last_timings.decode_ms == 12.5


def test_a_child_that_exits_during_a_decode_is_reported_as_crashed(make_worker, caplog):
    def die_on_job(process, message):
        if message[0] == "job":
            process.running = False
            process.exit_code = -11
            return None
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=die_on_job))

    worker = make_worker(transport)
    with caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER):
        with pytest.raises(WorkerCrashedError):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert "worker: child_exited phase=transcribe exit_code=-11" in caplog.text
        assert _child_running(worker) is False
        assert worker.is_model_ready is False
        assert transport.spawned[0].closes == [False]


def test_a_dead_child_is_replaced_on_the_next_request(make_worker, caplog):
    transport = FakeAsrTransport()

    worker = make_worker(transport)
    worker.warmup()
    first = transport.spawned[0]
    first.running = False
    first.exit_code = 3

    with caplog.at_level(logging.WARNING, logger=_WORKER_LOGGER):
        worker.warmup()

    assert "worker: replacing_child phase=respawn exit_code=3" in caplog.text
    assert len(transport.spawned) == 2
    # The new child is cold: its own model load is requested again.
    assert transport.spawned[1].sent == [("load", None)]
    assert worker.is_model_ready is True


def test_a_transport_that_cannot_spawn_fails_the_request_without_a_child(make_worker, caplog):
    transport = FakeAsrTransport(error=OSError("no such executable"))

    worker = make_worker(transport)
    with caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER):
        with pytest.raises(WorkerError, match="could not start ASR child"):
            worker.warmup()

        assert "worker: spawn_failed" in caplog.text
        assert _child_running(worker) is False
        assert worker.process_ids == ()


def test_a_failed_model_load_still_announces_that_loading_ended(make_worker):
    events, observers = _observed()
    transport = FakeAsrTransport(
        FakeAsrProcess(reply=lambda process, message: ("error", "inference", "RuntimeError: x"))
    )

    worker = make_worker(transport, **observers)
    with pytest.raises(WorkerError):
        worker.warmup()

    # Or the overlay keeps its loading border forever.
    assert events == ["model_loading", "model_loading_finished"]


def test_a_model_load_failure_keeps_the_child_and_is_typed_by_the_caller(make_worker):
    def fail_to_load(process, message):
        if message[0] == "load":
            return ("error", "inference", "RuntimeError: CUDA unavailable")
        return _reply_normally(process, message)

    transport = FakeAsrTransport(
        FakeAsrProcess(reply=fail_to_load), FakeAsrProcess(reply=fail_to_load)
    )

    warm_up_worker = make_worker(transport)
    # warmup surfaces the child's own error; transcribe re-types it so the
    # daemon can tell a model failure from a decode failure.
    with pytest.raises(WorkerError) as warmup_exc:
        warm_up_worker.warmup()
    assert not isinstance(warmup_exc.value, WorkerModelError)
    # A plain decode-side error does not poison the channel.
    assert _child_running(warm_up_worker) is True

    worker = make_worker(transport)
    with pytest.raises(WorkerModelError, match="model loading failed"):
        worker.transcribe(np.zeros(16000, dtype=np.float32))

    assert isinstance(worker.last_timings.load_ms, float)
    assert worker.last_timings.decode_ms is None
    assert worker.is_model_ready is False


def test_a_decode_error_keeps_the_child_for_the_next_utterance(make_worker):
    def fail_to_decode(process, message):
        if message[0] == "job":
            return ("error", "inference", "RuntimeError: boom")
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=fail_to_decode))

    worker = make_worker(transport)
    with pytest.raises(WorkerError) as exc:
        worker.transcribe(np.zeros(16000, dtype=np.float32))

    assert not isinstance(exc.value, (WorkerModelError, WorkerCrashedError))
    assert _child_running(worker) is True
    assert worker.is_model_ready is True
    assert transport.spawned[0].closes == []
    assert worker.last_timings.round_trip_ms is not None
    assert worker.last_timings.decode_ms is None


def test_a_slow_child_is_polled_until_it_answers(make_worker):
    transport = FakeAsrTransport(FakeAsrProcess(timeouts=3))

    worker = make_worker(transport)
    worker.warmup()

    # Three empty polls are not a failure; only the deadline is.
    assert transport.spawned[0].receives == 4
    assert worker.is_model_ready is True


def test_an_expired_deadline_ends_the_wait(make_worker, caplog):
    transport = FakeAsrTransport()

    worker = make_worker(transport)
    worker._begin_request()
    with (
        caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER),
        pytest.raises(WorkerTimeoutError, match="timed out during transcribe"),
    ):
        worker._wait_for_response("transcribe", deadline=time.monotonic() - 1.0)

    assert "worker: request_timeout phase=transcribe" in caplog.text


def test_a_timed_out_request_tears_the_child_down(make_worker, monkeypatch):
    monkeypatch.setattr(worker_module, "_MODEL_LOAD_TIMEOUT_SECONDS", 0.0)
    transport = FakeAsrTransport()

    worker = make_worker(transport)
    with pytest.raises(WorkerTimeoutError, match="timed out during model_load"):
        worker.warmup()

    assert transport.spawned[0].closes == [False]
    assert _child_running(worker) is False


@pytest.mark.parametrize("load_timeout, longest_poll", [(120.0, 0.1), (0.03, 0.03)])
def test_one_poll_never_outlasts_the_poll_interval_or_the_deadline(
    make_worker, monkeypatch, load_timeout, longest_poll
):
    monkeypatch.setattr(worker_module, "_MODEL_LOAD_TIMEOUT_SECONDS", load_timeout)
    polls: list[float] = []

    class _RecordingProcess(FakeAsrProcess):
        def receive(self, timeout: float):
            polls.append(timeout)
            return super().receive(timeout)

    worker = make_worker(FakeAsrTransport(_RecordingProcess()))
    worker.warmup()

    assert 0.0 < polls[0] <= longest_poll


def test_shutdown_closes_the_child_gracefully_and_refuses_later_requests(make_worker):
    transport = FakeAsrTransport()
    worker = make_worker(transport)
    worker.warmup()

    worker.shutdown()
    worker.shutdown()

    assert transport.spawned[0].closes == [True]
    assert _child_running(worker) is False
    with pytest.raises(WorkerError, match="shut down"):
        worker.warmup()
    assert len(transport.spawned) == 1


def test_shutdown_during_a_wait_abandons_the_in_flight_request(make_worker, caplog):
    holder: list[Worker] = []

    def shut_down_instead_of_answering(process, message):
        if message[0] == "job":
            holder[0]._shutdown_requested.set()
            return None
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=shut_down_instead_of_answering))

    worker = make_worker(transport)
    holder.append(worker)
    with (
        caplog.at_level(logging.INFO, logger=_WORKER_LOGGER),
        pytest.raises(WorkerError, match="shut down during transcribe"),
    ):
        worker.transcribe(np.zeros(16000, dtype=np.float32))

    assert "worker: cancelling phase=transcribe reason=shutdown" in caplog.text
    assert _child_running(worker) is False


def test_the_idle_timer_is_armed_only_while_a_live_child_is_unheld(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=60)
    worker.warmup()
    assert worker._idle_timer is not None
    assert worker._idle_timer.interval == 60

    worker.hold_model()
    worker._restart_idle_timer()
    assert worker._idle_timer is None

    worker.release_model()
    assert worker._idle_timer is not None


def test_idle_eviction_unloads_the_child(make_worker, caplog):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=60)
    worker.warmup()
    with caplog.at_level(logging.INFO, logger=_WORKER_LOGGER):
        worker._idle_kill()

    assert "worker: unload phase=idle" in caplog.text
    assert _child_running(worker) is False
    assert worker.is_model_ready is False
    assert transport.spawned[0].closes == [False]


def test_a_held_model_defers_eviction_and_schedules_a_retry(make_worker, caplog):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=60)
    worker.warmup()
    worker.hold_model()
    with caplog.at_level(logging.DEBUG, logger=_WORKER_LOGGER):
        worker._idle_kill()

    assert "worker: unload_deferred reason=recording" in caplog.text
    assert _child_running(worker) is True
    # A deferred unload must re-arm itself, or the child stays resident
    # until the process exits.
    assert worker._idle_timer is not None


def test_releasing_a_hold_arms_the_timer_even_when_the_lock_is_busy(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=60)
    worker.warmup()
    worker.hold_model()
    worker._restart_idle_timer()
    assert worker._idle_timer is None

    acquired = threading.Event()
    finish = threading.Event()

    def hold_the_lock():
        with worker._lock:
            acquired.set()
            finish.wait(5.0)

    blocker = threading.Thread(target=hold_the_lock, name="test-lock-holder")
    blocker.start()
    try:
        assert acquired.wait(5.0)
        # The caller holds the daemon lock here, so this must not block.
        worker.release_model()
        assert worker._idle_timer is None
    finally:
        finish.set()
        blocker.join(5.0)

    deadline = time.monotonic() + 5.0
    while worker._idle_timer is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker._idle_timer is not None


def test_a_worker_without_a_child_registers_no_process_ids(make_worker):
    worker = make_worker(FakeAsrTransport())
    assert worker.process_ids == ()
    assert _child_running(worker) is False
    assert worker.is_model_ready is False


def test_model_readiness_belongs_to_the_live_child(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport)
    worker.warmup()
    transport.spawned[0].running = False

    # The loaded model died with the child that held it.
    assert worker.is_model_ready is False


def test_a_child_that_dies_during_the_model_load_is_reported_as_crashed(make_worker):
    def die_on_load(process, message):
        process.running = False
        process.exit_code = -9
        return None

    transport = FakeAsrTransport(FakeAsrProcess(reply=die_on_load))

    worker = make_worker(transport)
    # A crash keeps its own type through transcribe: it is not a model
    # configuration problem the owner could fix.
    with pytest.raises(WorkerCrashedError):
        worker.transcribe(np.zeros(16000, dtype=np.float32))

    assert worker.last_timings.load_ms is not None
    assert worker.last_timings.decode_ms is None


def test_idle_unload_deadline_follows_the_armed_idle_timer(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=30.0)
    assert worker.idle_unload_deadline is None

    before = time.monotonic()
    worker.warmup()
    after = time.monotonic()
    assert before + 30.0 <= worker.idle_unload_deadline <= after + 30.0

    worker.hold_model()
    worker.warmup()
    assert worker.idle_unload_deadline is None

    worker.shutdown()
    assert worker.idle_unload_deadline is None


def test_idle_unload_deadline_clears_after_the_idle_unload(make_worker):
    transport = FakeAsrTransport()

    worker = make_worker(transport, idle_seconds=0.05)
    worker.warmup()
    assert worker.idle_unload_deadline is not None
    deadline = time.monotonic() + 2.0
    while _child_running(worker) and time.monotonic() < deadline:
        time.sleep(0.01)

    assert _child_running(worker) is False
    assert worker.idle_unload_deadline is None


def test_idle_unload_deadline_is_none_without_an_idle_timeout(make_worker):
    worker = make_worker(FakeAsrTransport(), idle_seconds=0.0)
    worker.warmup()
    assert worker.is_model_ready is True
    assert worker.idle_unload_deadline is None
