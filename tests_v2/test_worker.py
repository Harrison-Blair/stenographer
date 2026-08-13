# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for worker.py: classify_error + interpret_response only.

No process spawn, no Model, no network. The real lifecycle (spawn, decode
through the child, idle-kill, restart-if-dead) is covered by the integration
smoke suite in test_worker_smoke.py.
"""

from __future__ import annotations

import pytest
from stenographer_v2.model import PathologicalOutputError, TranscriptionResult
from stenographer_v2.worker import (
    WorkerError,
    WorkerPathologicalError,
    classify_error,
    interpret_response,
)


def test_interpret_response_returns_ok_result():
    result = TranscriptionResult(text="hi", duration_seconds=1.0, segments=[])
    assert interpret_response(("ok", result)) is result


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
        ("ok", secret, "extra"),
        ("error", "mystery", secret),
    ):
        with pytest.raises(WorkerError) as exc:
            interpret_response(message)
        assert secret not in str(exc.value)
        assert "shape" in str(exc.value)


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
