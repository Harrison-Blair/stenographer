# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the worker protocol, lifecycle, and timeout policies.

No process spawn, no Model, no network. The real lifecycle (spawn, decode
through the child, idle-kill, restart-if-dead) is covered by the integration
smoke suite in test_worker_smoke.py.
"""

from __future__ import annotations

import pytest

from stenographer.transcribe.model import PathologicalOutputError, TranscriptionResult
from stenographer.transcribe.worker import (
    _MODEL_LOAD_TIMEOUT_SECONDS,
    WorkerError,
    WorkerEvent,
    WorkerLifecycle,
    WorkerPathologicalError,
    WorkerProtocolError,
    _WorkerTimeoutError,
    classify_error,
    decode_timeout_seconds,
    interpret_response,
    lifecycle_transition,
    response_poll_timeout,
    should_arm_idle_timer,
    should_teardown_for_response_error,
)


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


def test_model_load_timeout_is_two_minutes():
    assert _MODEL_LOAD_TIMEOUT_SECONDS == 120.0


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
