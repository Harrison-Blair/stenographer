# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-job cancellation tests for :class:`stenographer.asr.worker.Worker`.

Uses a stub model so no ASR weights are needed.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from stenographer.asr.model import SegmentInfo, TranscriptionResult, WordInfo
from stenographer.asr.worker import CancelledError, Worker


class _StubModel:
    """Emits two segments through on_segment, then returns a result."""

    language = "en"
    beam_size = 1

    def __init__(self) -> None:
        self.transcribe_calls = 0
        self.transcribe_words_calls = 0
        self.word_beam_sizes: list[int | None] = []
        # Optional hook fired between the two "segments" of a word decode.
        self.between_word_segments = None

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

    def transcribe_words(self, samples, *, beam_size=None, check_cancel=None):
        self.transcribe_words_calls += 1
        self.word_beam_sizes.append(beam_size)
        words = []
        for i, (word, hook) in enumerate(
            [(" hello", self.between_word_segments), (" world", None)]
        ):
            if check_cancel is not None:
                check_cancel()
            words.append(WordInfo(start=i * 0.5, end=(i + 1) * 0.5, word=word, probability=1.0))
            if hook is not None:
                hook()
        return words

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


def test_submit_words_returns_word_list_and_passes_beam_size() -> None:
    model = _StubModel()
    worker = Worker(model)
    worker.start()
    try:
        fut = worker.submit_words(np.zeros(16000, dtype=np.float32), beam_size=2)
        words = fut.result(timeout=5.0)
        assert [w.word for w in words] == [" hello", " world"]
        assert model.word_beam_sizes == [2]
    finally:
        worker.stop(timeout=5.0)


def test_word_job_cancel_event_aborts_mid_decode() -> None:
    model = _StubModel()
    worker = Worker(model)
    worker.start()
    try:
        cancel = threading.Event()
        model.between_word_segments = cancel.set  # fires after the first word
        fut = worker.submit_words(np.zeros(16000, dtype=np.float32), cancel_event=cancel)
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)

        # The worker survives a per-job cancel: the next word job runs normally.
        model.between_word_segments = None
        fut2 = worker.submit_words(np.zeros(16000, dtype=np.float32))
        assert [w.word for w in fut2.result(timeout=5.0)] == [" hello", " world"]
    finally:
        worker.stop(timeout=5.0)


def test_word_job_cancelled_before_pickup_skips_model() -> None:
    model = _StubModel()
    worker = Worker(model)
    cancel = threading.Event()
    cancel.set()
    fut = worker.submit_words(np.zeros(16000, dtype=np.float32), cancel_event=cancel)
    worker.start()
    try:
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)
        assert model.transcribe_words_calls == 0
    finally:
        worker.stop(timeout=5.0)


def test_final_word_job_survives_global_cancel() -> None:
    """Shutdown cancels interim re-decodes but must not discard the utterance.

    ``Session.stop`` hands the finalized samples to the incremental driver and
    then calls ``Worker.cancel``. Without the exemption the driver's final
    decode is cancelled before it runs and the whole dictation is lost.
    """
    model = _StubModel()
    worker = Worker(model)
    worker.cancel()  # the sticky global cancel Session.stop() fires
    fut = worker.submit_words(np.zeros(16000, dtype=np.float32), ignore_global_cancel=True)
    worker.start()
    try:
        assert [w.word for w in fut.result(timeout=5.0)] == [" hello", " world"]
        assert model.transcribe_words_calls == 1
    finally:
        worker.stop(timeout=5.0)


def test_global_cancel_still_aborts_unflagged_word_jobs() -> None:
    """The exemption is opt-in: interim re-decodes stay cancellable."""
    model = _StubModel()
    worker = Worker(model)
    worker.cancel()
    fut = worker.submit_words(np.zeros(16000, dtype=np.float32))
    worker.start()
    try:
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)
        assert model.transcribe_words_calls == 0
    finally:
        worker.stop(timeout=5.0)


def test_final_word_job_still_honors_its_own_cancel_event() -> None:
    """Exempting the global cancel must not make a job uncancellable.

    A genuine abort (recorder failure) fires the driver's per-job event, and
    that must still stop the decode.
    """
    model = _StubModel()
    worker = Worker(model)
    cancel = threading.Event()
    cancel.set()
    fut = worker.submit_words(
        np.zeros(16000, dtype=np.float32), cancel_event=cancel, ignore_global_cancel=True
    )
    worker.start()
    try:
        with pytest.raises(CancelledError):
            fut.result(timeout=5.0)
        assert model.transcribe_words_calls == 0
    finally:
        worker.stop(timeout=5.0)
