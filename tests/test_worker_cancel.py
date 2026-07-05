# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-job cancellation tests for :class:`stenographer.asr.worker.Worker`.

Uses a stub model so no ASR weights are needed.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from stenographer.asr.model import SegmentInfo, TranscriptionResult
from stenographer.asr.worker import CancelledError, Worker


class _StubModel:
    """Emits two segments through on_segment, then returns a result."""

    language = "en"
    beam_size = 1

    def __init__(self) -> None:
        self.transcribe_calls = 0

    def transcribe(self, samples, language, beam_size, on_segment=None):
        self.transcribe_calls += 1
        segments = [
            SegmentInfo(0.0, 0.5, " hello", 0.1),
            SegmentInfo(0.5, 1.0, " world", 0.1),
        ]
        if on_segment is not None:
            for seg in segments:
                on_segment(seg)
        return TranscriptionResult(text="hello world", duration_seconds=1.0, segments=segments)

    def close(self) -> None:
        pass


def test_job_cancel_event_aborts_mid_stream_and_next_job_runs() -> None:
    model = _StubModel()
    worker = Worker(model)
    worker.start()
    try:
        cancel = threading.Event()
        seen: list[str] = []

        def on_segment(seg: SegmentInfo) -> None:
            seen.append(seg.text)
            cancel.set()  # cancel after the first segment

        fut = worker.submit(
            np.zeros(16000, dtype=np.float32), on_segment=on_segment, cancel_event=cancel
        )
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)
        assert seen == [" hello"]  # second segment never delivered

        # The worker survives a per-job cancel: the next job runs normally.
        fut2 = worker.submit(np.zeros(16000, dtype=np.float32))
        result = fut2.result(timeout=5.0)
        assert result.text == "hello world"
    finally:
        worker.stop(timeout=5.0)


def test_job_cancelled_before_pickup_skips_model() -> None:
    model = _StubModel()
    worker = Worker(model)
    cancel = threading.Event()
    cancel.set()
    fut = worker.submit(np.zeros(16000, dtype=np.float32), cancel_event=cancel)
    worker.start()  # job was queued before the worker thread ran
    try:
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)
        assert model.transcribe_calls == 0
    finally:
        worker.stop(timeout=5.0)
