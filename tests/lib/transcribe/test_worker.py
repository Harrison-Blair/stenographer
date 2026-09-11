# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the worker protocol, lifecycle, and timeout policies.

No process spawn, no Model, no network. The real lifecycle (spawn, decode
through the child, idle-kill, restart-if-dead) is covered by the integration
smoke suite in test_worker_smoke.py.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.transcribe.errors import (
    PathologicalOutputError,
    WorkerCrashedError,
    WorkerError,
    WorkerModelError,
    WorkerPathologicalError,
    WorkerProtocolError,
    _WorkerTimeoutError,
)
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker import Worker
from stenographer.lib.transcribe.worker_event import WorkerEvent
from stenographer.lib.transcribe.worker_lifecycle import WorkerLifecycle
from stenographer.lib.transcribe.worker_policy import (
    classify_error,
    decode_timeout_seconds,
    error_is_safe_to_render,
    interpret_response,
    lifecycle_transition,
    response_poll_timeout,
    should_arm_idle_timer,
    should_teardown_for_response_error,
)

_WORKER_LOGGER = "stenographer.lib.transcribe.worker"


def test_lifecycle_observer_failure_is_logged_and_suppressed(caplog):
    observed = []

    def raising_observer():
        raise RuntimeError("observer failed")

    worker = Worker(
        Config.loads("").asr,
        on_model_loading=raising_observer,
        on_model_ready=lambda: observed.append("ready"),
    )
    with caplog.at_level(logging.WARNING, logger="stenographer.lib.transcribe.worker"):
        worker._emit_lifecycle((WorkerLifecycle.MODEL_LOADING, WorkerLifecycle.MODEL_READY))
    assert observed == ["ready"]
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "worker: lifecycle_callback_failed" in messages[0]
    assert "lifecycle_event=model_loading" in messages[0]
    assert 'error=RuntimeError detail="observer failed"' in messages[0]


def test_interpret_response_returns_ok_result():
    result = TranscriptionResult(text="hi", duration_seconds=1.0, segments=[])
    assert interpret_response(("ok", result)) is result


def test_interpret_response_returns_metadata_only_model_ready_event():
    assert interpret_response(("model_ready",)) is WorkerEvent.MODEL_READY


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


def test_interpret_response_malformed_raises_worker_error():
    # Unknown tag, wrong arity, and an unknown error kind must all raise
    # WorkerError without echoing any payload value into the message.
    secret = "the dictated transcript text"
    for message in (
        ("bogus",),
        ("ok",),
        ("ok", secret),
        ("ok", secret, "extra"),
        ("error", "mystery", secret),
        ("error", "inference", object()),
        ("model_ready", secret),
    ):
        with pytest.raises(WorkerProtocolError) as exc:
            interpret_response(message)
        assert secret not in str(exc.value)
        assert "shape" in str(exc.value)


def test_legitimate_worker_errors_do_not_become_protocol_errors():
    for message in (
        ("error", "inference", "RuntimeError: boom"),
        ("error", "pathological", "decoder density exceeded"),
    ):
        with pytest.raises(WorkerError) as exc:
            interpret_response(message)
        assert not isinstance(exc.value, WorkerProtocolError)
        assert should_teardown_for_response_error(exc.value) is False


def test_malformed_worker_errors_require_teardown():
    with pytest.raises(WorkerProtocolError) as exc:
        interpret_response(("bogus", "secret"))
    assert should_teardown_for_response_error(exc.value) is True


def test_timeout_errors_require_teardown():
    assert should_teardown_for_response_error(_WorkerTimeoutError("timed out")) is True


def test_decode_timeout_has_sixty_second_floor():
    assert decode_timeout_seconds(0) == 60.0
    assert decode_timeout_seconds(16_000 * 10) == 60.0
    assert decode_timeout_seconds(16_000 * 15) == 60.0


def test_decode_timeout_is_four_times_actual_audio_duration():
    assert decode_timeout_seconds(16_000 * 20) == 80.0
    assert decode_timeout_seconds(16_000 * 125) == 500.0


def test_response_poll_timeout_clamps_to_remaining_deadline():
    assert response_poll_timeout(now=100.0, deadline=200.0) == 0.1
    assert response_poll_timeout(now=100.0, deadline=100.03) == pytest.approx(0.03)
    assert response_poll_timeout(now=100.0, deadline=100.0) == 0.0
    assert response_poll_timeout(now=100.0, deadline=99.0) == 0.0


def test_cold_and_warm_lifecycle_ordering():
    cold_start = lifecycle_transition(model_loaded=False)
    cold_ready = lifecycle_transition(model_loaded=False, event=WorkerEvent.MODEL_READY)
    assert cold_start + cold_ready == (
        WorkerLifecycle.MODEL_LOADING,
        WorkerLifecycle.MODEL_READY,
    )
    assert lifecycle_transition(model_loaded=True) == ()


def test_duplicate_model_ready_is_a_protocol_error():
    with pytest.raises(WorkerProtocolError):
        lifecycle_transition(model_loaded=True, event=WorkerEvent.MODEL_READY)


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


def test_malformed_non_tuple_responses_are_described_by_type_only():
    secret = "the dictated transcript text"
    with pytest.raises(WorkerProtocolError) as exc:
        interpret_response(secret)

    assert secret not in str(exc.value)
    assert str(exc.value) == "malformed worker response of shape str"


class FakeAsrProcess:
    """One ASR child as a pair of real queues, a pid, and a liveness flag.

    It is the ``AsrProcess`` the transport hands back; the parent-side policy
    under test never learns whether a real process is behind it. Real process
    lifecycle stays in the smoke suite.
    """

    def __init__(self, *, pid: int = 4321, reply=None, timeouts: int = 0) -> None:
        self.pid = pid
        self.exit_code: int | None = None
        self.running = True
        self.sent: list[tuple] = []
        self.closes: list[bool] = []
        self.receives = 0
        self.timeouts = timeouts
        self._reply = reply if reply is not None else _reply_normally
        self._responses: queue.Queue = queue.Queue()

    def is_running(self) -> bool:
        return self.running

    def send(self, message: tuple) -> None:
        self.sent.append(message)
        response = self._reply(self, message)
        if response is not None:
            self._responses.put(response)

    def receive(self, timeout: float):
        self.receives += 1
        if self.timeouts > 0:
            self.timeouts -= 1
            raise TimeoutError("no response yet")
        try:
            return self._responses.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("no response yet") from None

    def close(self, graceful: bool = False) -> None:
        self.closes.append(graceful)
        self.running = False


class FakeAsrTransport:
    """Hands out prepared children instead of spawning real ones."""

    def __init__(self, *children, error: Exception | None = None) -> None:
        self.pending = list(children)
        self.error = error
        self.spawned: list[FakeAsrProcess] = []
        self.log_sinks: list[object] = []

    def spawn(self, config, *, on_log):
        if self.error is not None:
            raise self.error
        child = self.pending.pop(0) if self.pending else FakeAsrProcess()
        self.spawned.append(child)
        self.log_sinks.append(on_log)
        return child


def _result(text: str = "hello there") -> TranscriptionResult:
    return TranscriptionResult(text=text, duration_seconds=1.0, segments=[], inference_ms=12.5)


def _reply_normally(process: FakeAsrProcess, message: tuple):
    if message[0] == "load":
        return ("model_ready",)
    if message[0] == "job":
        return ("ok", _result())
    return None


def _worker(transport, *, idle_seconds: float = 0.0, **observers) -> Worker:
    cfg = replace(Config.loads("").asr, idle_unload_seconds=idle_seconds)
    return Worker(cfg, transport=transport, **observers)


def _observed() -> tuple[list[str], dict]:
    events: list[str] = []
    observers = {
        name: (lambda event=event: events.append(event))
        for name, event in (
            ("on_model_loading", "model_loading"),
            ("on_model_ready", "model_ready"),
            ("on_model_loading_finished", "model_loading_finished"),
            ("on_transcribing", "transcribing"),
        )
    }
    return events, observers


def test_warmup_loads_the_model_and_announces_the_lifecycle_in_order():
    events, observers = _observed()
    transport = FakeAsrTransport()

    with _worker(transport, **observers) as worker:
        worker.warmup(7)

        assert transport.spawned[0].sent == [("load", 7)]
        assert events == ["model_loading", "model_ready", "model_loading_finished"]
        assert worker.is_model_ready is True
        assert worker.is_alive() is True
        assert worker.process_ids == (4321,)


def test_a_second_warmup_reuses_the_already_loaded_model():
    events, observers = _observed()
    transport = FakeAsrTransport()

    with _worker(transport, **observers) as worker:
        worker.warmup()
        worker.warmup()

        assert transport.spawned[0].sent == [("load", None)]
        assert events == ["model_loading", "model_ready", "model_loading_finished"]
        assert len(transport.spawned) == 1


def test_a_cold_transcription_loads_then_decodes_and_measures_both():
    events, observers = _observed()
    transport = FakeAsrTransport()

    with _worker(transport, **observers) as worker:
        result = worker.transcribe(np.zeros(16000, dtype=np.float32), 5)

        child = transport.spawned[0]
        assert [message[0] for message in child.sent] == ["load", "job"]
        assert child.sent[1][2] == 5
        assert result.text == "hello there"
        assert events == [
            "model_loading",
            "model_ready",
            "model_loading_finished",
            "transcribing",
        ]
        timings = worker.last_timings
        assert timings is not None
        assert timings.load_ms is not None
        # decode_ms is the child's own inference measurement, not a round trip.
        assert timings.decode_ms == 12.5
        assert timings.round_trip_ms is not None
        assert timings.lock_wait_ms >= 0.0


def test_a_warm_transcription_reports_no_load_of_its_own():
    transport = FakeAsrTransport()

    with _worker(transport) as worker:
        worker.warmup()
        worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert [message[0] for message in transport.spawned[0].sent] == ["load", "job"]
        assert worker.last_timings.load_ms is None
        assert worker.last_timings.decode_ms == 12.5


def test_a_child_that_exits_during_a_decode_is_reported_as_crashed(caplog):
    def die_on_job(process, message):
        if message[0] == "job":
            process.running = False
            process.exit_code = -11
            return None
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=die_on_job))

    with _worker(transport) as worker, caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER):
        with pytest.raises(WorkerCrashedError):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert "worker: child_exited phase=transcribe exit_code=-11" in caplog.text
        assert worker.is_alive() is False
        assert worker.is_model_ready is False
        assert transport.spawned[0].closes == [False]


def test_a_dead_child_is_replaced_on_the_next_request(caplog):
    transport = FakeAsrTransport()

    with _worker(transport) as worker:
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


def test_a_transport_that_cannot_spawn_fails_the_request_without_a_child(caplog):
    transport = FakeAsrTransport(error=OSError("no such executable"))

    with _worker(transport) as worker, caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER):
        with pytest.raises(WorkerError, match="could not start ASR child"):
            worker.warmup()

        assert "worker: spawn_failed" in caplog.text
        assert worker.is_alive() is False
        assert worker.process_ids == ()


def test_a_malformed_response_poisons_the_channel_and_tears_the_child_down():
    events, observers = _observed()
    transport = FakeAsrTransport(FakeAsrProcess(reply=lambda process, message: ("gibberish",)))

    with _worker(transport, **observers) as worker:
        with pytest.raises(WorkerProtocolError):
            worker.warmup()

        # The observer must still be told loading ended, or the overlay keeps
        # its loading border forever.
        assert events == ["model_loading", "model_loading_finished"]
        assert transport.spawned[0].closes == [False]
        assert worker.is_alive() is False


def test_a_model_load_failure_keeps_the_child_and_is_typed_by_the_caller():
    def fail_to_load(process, message):
        if message[0] == "load":
            return ("error", "inference", "RuntimeError: CUDA unavailable")
        return _reply_normally(process, message)

    transport = FakeAsrTransport(
        FakeAsrProcess(reply=fail_to_load), FakeAsrProcess(reply=fail_to_load)
    )

    with _worker(transport) as warm_up_worker:
        # warmup surfaces the child's own error; transcribe re-types it so the
        # daemon can tell a model failure from a decode failure.
        with pytest.raises(WorkerError) as warmup_exc:
            warm_up_worker.warmup()
        assert not isinstance(warmup_exc.value, WorkerModelError)
        # A plain decode-side error does not poison the channel.
        assert warm_up_worker.is_alive() is True

    with _worker(transport) as worker:
        with pytest.raises(WorkerModelError, match="model loading failed"):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert isinstance(worker.last_timings.load_ms, float)
        assert worker.last_timings.decode_ms is None
        assert worker.is_model_ready is False


def test_a_decode_error_keeps_the_child_for_the_next_utterance():
    def fail_to_decode(process, message):
        if message[0] == "job":
            return ("error", "inference", "RuntimeError: boom")
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=fail_to_decode))

    with _worker(transport) as worker:
        with pytest.raises(WorkerError) as exc:
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert not isinstance(exc.value, (WorkerModelError, WorkerCrashedError))
        assert worker.is_alive() is True
        assert worker.is_model_ready is True
        assert transport.spawned[0].closes == []
        assert worker.last_timings.round_trip_ms is not None
        assert worker.last_timings.decode_ms is None


def test_a_slow_child_is_polled_until_it_answers():
    transport = FakeAsrTransport(FakeAsrProcess(timeouts=3))

    with _worker(transport) as worker:
        worker.warmup()

        # Three empty polls are not a failure; only the deadline is.
        assert transport.spawned[0].receives == 4
        assert worker.is_model_ready is True


def test_an_expired_deadline_ends_the_wait(caplog):
    transport = FakeAsrTransport()

    with _worker(transport) as worker:
        worker._begin_request()
        with (
            caplog.at_level(logging.ERROR, logger=_WORKER_LOGGER),
            pytest.raises(_WorkerTimeoutError, match="timed out during transcribe"),
        ):
            worker._wait_for_response("transcribe", deadline=time.monotonic() - 1.0)

        assert "worker: request_timeout phase=transcribe" in caplog.text


def test_shutdown_closes_the_child_gracefully_and_refuses_later_requests():
    transport = FakeAsrTransport()
    worker = _worker(transport)
    worker.warmup()

    worker.shutdown()
    worker.shutdown()

    assert transport.spawned[0].closes == [True]
    assert worker.is_alive() is False
    with pytest.raises(WorkerError, match="shut down"):
        worker.warmup()
    assert len(transport.spawned) == 1


def test_shutdown_during_a_wait_abandons_the_in_flight_request(caplog):
    holder: list[Worker] = []

    def shut_down_instead_of_answering(process, message):
        if message[0] == "job":
            holder[0]._shutdown_requested.set()
            return None
        return _reply_normally(process, message)

    transport = FakeAsrTransport(FakeAsrProcess(reply=shut_down_instead_of_answering))

    with _worker(transport) as worker:
        holder.append(worker)
        with (
            caplog.at_level(logging.INFO, logger=_WORKER_LOGGER),
            pytest.raises(WorkerError, match="shut down during transcribe"),
        ):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert "worker: cancelling phase=transcribe reason=shutdown" in caplog.text
        assert worker.is_alive() is False


def test_the_idle_timer_is_armed_only_while_a_live_child_is_unheld():
    transport = FakeAsrTransport()

    with _worker(transport, idle_seconds=60) as worker:
        worker.warmup()
        assert worker._idle_timer is not None
        assert worker._idle_timer.interval == 60

        worker.hold_model()
        worker._restart_idle_timer()
        assert worker._idle_timer is None

        worker.release_model()
        assert worker._idle_timer is not None


def test_idle_eviction_unloads_the_child(caplog):
    transport = FakeAsrTransport()

    with _worker(transport, idle_seconds=60) as worker:
        worker.warmup()
        with caplog.at_level(logging.INFO, logger=_WORKER_LOGGER):
            worker._idle_kill()

        assert "worker: unload phase=idle" in caplog.text
        assert worker.is_alive() is False
        assert worker.is_model_ready is False
        assert transport.spawned[0].closes == [False]


def test_a_held_model_defers_eviction_and_schedules_a_retry(caplog):
    transport = FakeAsrTransport()

    with _worker(transport, idle_seconds=60) as worker:
        worker.warmup()
        worker.hold_model()
        with caplog.at_level(logging.DEBUG, logger=_WORKER_LOGGER):
            worker._idle_kill()

        assert "worker: unload_deferred reason=recording" in caplog.text
        assert worker.is_alive() is True
        # A deferred unload must re-arm itself, or the child stays resident
        # until the process exits.
        assert worker._idle_timer is not None


def test_an_armed_timer_really_evicts_the_child():
    transport = FakeAsrTransport()

    # A sub-second idle budget: the same arming policy the configured seconds
    # use, shortened so the timer can actually be observed firing.
    with _worker(transport, idle_seconds=0.05) as worker:
        worker.warmup()

        deadline = time.monotonic() + 5.0
        while worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)

        assert worker.is_alive() is False
        assert transport.spawned[0].closes == [False]


def test_releasing_a_hold_arms_the_timer_even_when_the_lock_is_busy():
    transport = FakeAsrTransport()

    with _worker(transport, idle_seconds=60) as worker:
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


def test_a_worker_without_a_child_registers_no_process_ids():
    with _worker(FakeAsrTransport()) as worker:
        assert worker.process_ids == ()
        assert worker.is_alive() is False
        assert worker.is_model_ready is False


def test_model_readiness_belongs_to_the_live_child():
    transport = FakeAsrTransport()

    with _worker(transport) as worker:
        worker.warmup()
        transport.spawned[0].running = False

        # The loaded model died with the child that held it.
        assert worker.is_model_ready is False


def test_a_child_that_dies_during_the_model_load_is_reported_as_crashed():
    def die_on_load(process, message):
        process.running = False
        process.exit_code = -9
        return None

    transport = FakeAsrTransport(FakeAsrProcess(reply=die_on_load))

    with _worker(transport) as worker:
        # A crash keeps its own type through transcribe: it is not a model
        # configuration problem the owner could fix.
        with pytest.raises(WorkerCrashedError):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        assert worker.last_timings.load_ms is not None
        assert worker.last_timings.decode_ms is None


def test_a_result_before_the_ready_event_is_a_protocol_error():
    transport = FakeAsrTransport(FakeAsrProcess(reply=lambda process, message: ("ok", _result())))

    with _worker(transport) as worker:
        with pytest.raises(WorkerProtocolError, match="before model-ready event"):
            worker.warmup()

        assert transport.spawned[0].closes == [False]


def test_a_ready_event_answering_a_decode_is_a_protocol_error():
    def ready_instead_of_result(process, message):
        return ("model_ready",)

    transport = FakeAsrTransport(FakeAsrProcess(reply=ready_instead_of_result))

    with _worker(transport) as worker:
        worker.warmup()

        with pytest.raises(WorkerProtocolError, match="during transcription"):
            worker.transcribe(np.zeros(16000, dtype=np.float32))

        # A poisoned channel is torn down rather than reused.
        assert worker.is_alive() is False
