# SPDX-License-Identifier: GPL-3.0-or-later
"""The ASR child's request loop, run in-process over real queues.

``_child_main`` is a plain loop over two queues, so it runs here on real
``queue.Queue`` objects with no process. The native model is replaced by a
stand-in whose decode fails, because a real load stays the integration smoke
suite's job. The child's own logger configuration is global to the interpreter,
so it is saved and restored around each run.
"""

from __future__ import annotations

import logging
import queue

import numpy as np
import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.logging import pipeline
from stenographer.lib.platform.asr import _child_main
from stenographer.lib.transcribe import model as model_module

_DECODE_ERROR = "decoder said: the quick brown fox"


class _FailingModel:
    cpu_threads = 1

    def __init__(self, cfg) -> None:
        pass

    def transcribe(self, samples):
        raise RuntimeError(_DECODE_ERROR)


@pytest.fixture
def failing_model(monkeypatch):
    monkeypatch.setattr(model_module, "Model", _FailingModel)


def _run_child(requests: list[tuple]) -> tuple[queue.Queue, list[logging.LogRecord], queue.Queue]:
    """Run the child loop to completion over prepared queues."""
    request_q: queue.Queue = queue.Queue()
    response_q: queue.Queue = queue.Queue()
    log_q: queue.Queue = queue.Queue()
    for request in requests:
        request_q.put(request)
    logger = logging.getLogger("stenographer")
    # The child's own configuration closes whatever handlers it finds, so any
    # handler installed here is detached before the run and re-attached after:
    # nothing this test hands back has been closed behind its owner's back.
    detached = list(logger.handlers)
    for handler in detached:
        logger.removeHandler(handler)
    level, propagate = logger.level, logger.propagate
    try:
        _child_main(Config.loads("").asr, request_q, response_q, log_q, logging.DEBUG)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in detached:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate
        pipeline.set_utterance(None)
    records = []
    while not log_q.empty():
        records.append(log_q.get_nowait())
    return response_q, records, request_q


def _drain(responses: queue.Queue) -> list[object]:
    drained = []
    while not responses.empty():
        drained.append(responses.get_nowait())
    return drained


def test_stop_ends_the_loop_without_answering_anything():
    responses, records, requests = _run_child([("stop",), ("job", np.zeros(4), 1)])

    assert _drain(responses) == []
    assert records == []
    # The request after the stop is left untouched rather than served.
    assert requests.qsize() == 1


@pytest.mark.usefixtures("failing_model")
def test_a_failed_decode_is_answered_and_the_child_stays_alive():
    samples = np.zeros(16000, dtype=np.float32)

    responses, _records, _requests = _run_child(
        [("load", 3), ("job", samples, 4), ("job", samples, 5), ("stop",)]
    )

    # Both requests are answered: a failed decode must not end the child, or
    # the parent would respawn a healthy process for one bad request.
    assert _drain(responses) == [
        ("model_ready",),
        ("error", "inference", f"RuntimeError: {_DECODE_ERROR}"),
        ("error", "inference", f"RuntimeError: {_DECODE_ERROR}"),
    ]


@pytest.mark.usefixtures("failing_model")
def test_each_failure_is_logged_under_the_requesting_utterance():
    samples = np.zeros(16000, dtype=np.float32)

    _responses, records, _requests = _run_child(
        [("load", 3), ("job", samples, 4), ("job", samples, 5), ("stop",)]
    )

    failures = [record for record in records if "asr: job_failed" in record.getMessage()]
    assert len(failures) == 2
    assert [record.levelno for record in failures] == [logging.ERROR, logging.ERROR]
    # The child stamps the parent's utterance id so its lines interleave with
    # the daemon's under the same utt=N.
    assert [record.utt_suffix for record in failures] == [" utt=4", " utt=5"]
    assert "phase=decode" in failures[0].getMessage()


@pytest.mark.usefixtures("failing_model")
def test_a_decode_failure_never_renders_the_exception_message():
    # The decode lineage can quote audio-derived text, so only the class name
    # and the traceback frames may be logged.
    samples = np.zeros(16000, dtype=np.float32)

    _responses, records, _requests = _run_child([("load", 3), ("job", samples, 4), ("stop",)])

    message = next(r.getMessage() for r in records if "asr: job_failed" in r.getMessage())
    assert "error=RuntimeError" in message
    assert "frames=asr.py:" in message
    assert "detail=" not in message
    assert _DECODE_ERROR not in message


@pytest.mark.usefixtures("failing_model")
@pytest.mark.parametrize("utterance", [None, 12])
def test_the_failure_response_carries_no_audio(utterance):
    samples = np.full(16000, 0.5, dtype=np.float32)

    responses, _records, _requests = _run_child(
        [("load", 3), ("job", samples, utterance), ("stop",)]
    )

    (kind, category, detail) = _drain(responses)[1]
    assert (kind, category) == ("error", "inference")
    assert detail == f"RuntimeError: {_DECODE_ERROR}"
