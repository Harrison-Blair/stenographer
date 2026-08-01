# SPDX-License-Identifier: GPL-3.0-or-later
"""Restart, timeout, and shutdown tests for spawned ASR inference."""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from stenographer.asr.model import WordInfo
from stenographer.asr.streaming import StreamingTranscriber
from stenographer.asr.worker import (
    ASRProcessError,
    ASRTimeoutError,
    CancelledError,
    ProcessWorker,
)
from stenographer.config import Config
from stenographer.live import IncrementalDriver
from stenographer.output.formatter import HeuristicFormatter


def _stub_child(cfg, eager, idle_unload_seconds, commands, responses, log_records) -> None:
    del cfg, idle_unload_seconds, log_records
    if eager:
        responses.put(("loaded",))
    while True:
        try:
            command = commands.get(timeout=5)
        except queue.Empty:
            continue
        if command[0] == "stop":
            return
        if command[0] == "load":
            responses.put(("loaded",))
            continue
        if command[0] == "unload":
            responses.put(("unloaded",))
            continue
        _name, job_id, samples, _kind, _beam, _purpose = command
        marker = int(samples.reshape(-1)[0])
        responses.put(("loaded",))
        if marker == 1:
            time.sleep(60)
        if marker == 5:
            time.sleep(0.2)
        if marker == 3:
            os._exit(17)
        responses.put(
            (
                "result",
                job_id,
                [WordInfo(start=0.0, end=0.25, word=" ok", probability=1.0)],
            )
        )


def _worker() -> ProcessWorker:
    cfg = Config.defaults()
    worker = ProcessWorker(cfg.asr, child_target=_stub_child)
    worker.start()
    return worker


def _samples(marker: int) -> np.ndarray:
    return np.full(160, marker, dtype=np.float32)


def test_timeout_kills_child_and_next_job_runs() -> None:
    worker = _worker()
    try:
        first_pid = worker._process.pid
        future = worker.submit_words(
            _samples(1), deadline=time.monotonic() + 0.2, priority="interim"
        )
        with pytest.raises(ASRTimeoutError):
            future.result(timeout=2)

        recovered = worker.submit_words(
            _samples(2), deadline=time.monotonic() + 2, priority="final"
        )
        assert [word.word for word in recovered.result(timeout=3)] == [" ok"]
        assert worker._process.pid != first_pid
    finally:
        worker.stop(timeout=2)


def test_release_supersedes_blocked_interim_and_runs_final() -> None:
    worker = _worker()
    try:
        interim = worker.submit_words(
            _samples(1), deadline=time.monotonic() + 5, priority="interim"
        )
        time.sleep(0.1)
        worker.supersede_interim()
        final = worker.submit_words(_samples(2), deadline=time.monotonic() + 2, priority="final")
        with pytest.raises(CancelledError):
            interim.result(timeout=2)
        assert final.result(timeout=3)[0].word == " ok"
    finally:
        worker.stop(timeout=2)


def test_release_grace_retains_an_interim_that_finishes_promptly() -> None:
    worker = _worker()
    try:
        pid = worker._process.pid
        interim = worker.submit_words(
            _samples(5), deadline=time.monotonic() + 2, priority="interim"
        )
        time.sleep(0.05)
        worker.supersede_interim(grace_seconds=0.5)

        assert interim.result(timeout=2)[0].word == " ok"
        assert worker._process.pid == pid
    finally:
        worker.stop(timeout=2)


def test_release_grace_forces_restart_after_bound() -> None:
    worker = _worker()
    try:
        pid = worker._process.pid
        interim = worker.submit_words(
            _samples(1), deadline=time.monotonic() + 5, priority="interim"
        )
        time.sleep(0.05)
        started = time.monotonic()
        worker.supersede_interim(grace_seconds=0.1)
        final = worker.submit_words(_samples(2), deadline=time.monotonic() + 2, priority="final")

        with pytest.raises(CancelledError):
            interim.result(timeout=2)
        assert time.monotonic() - started < 0.5
        assert final.result(timeout=3)[0].word == " ok"
        assert worker._process.pid != pid
    finally:
        worker.stop(timeout=2)


def test_native_crash_resolves_future_and_worker_reloads() -> None:
    worker = _worker()
    try:
        crashed = worker.submit_words(_samples(3), deadline=time.monotonic() + 2, priority="final")
        with pytest.raises(ASRProcessError, match="child exited"):
            crashed.result(timeout=3)
        assert worker.submit_words(_samples(2), priority="final").result(timeout=3)
    finally:
        worker.stop(timeout=2)


def test_shutdown_resolves_active_and_queued_futures() -> None:
    worker = _worker()
    active = worker.submit_words(_samples(1), priority="final")
    queued = worker.submit_words(_samples(2), priority="interim")
    time.sleep(0.1)
    worker.stop(timeout=0.1)

    assert active.done()
    assert queued.done()
    assert not worker.is_running
    assert worker._process is None


def test_model_state_callbacks_cross_process_boundary() -> None:
    worker = _worker()
    loaded = threading.Event()
    unloaded = threading.Event()
    try:
        worker.ensure_model_loaded(on_loaded=loaded.set, on_unloaded=unloaded.set)
        assert loaded.wait(timeout=2)
        assert worker.is_model_loaded()
        worker.request_unload()
        assert unloaded.wait(timeout=2)
        assert not worker.is_model_loaded()
    finally:
        worker.stop(timeout=2)


def test_job_cancel_event_before_pickup_is_rejected() -> None:
    worker = _worker()
    try:
        cancel = threading.Event()
        cancel.set()
        future = worker.submit_words(_samples(2), cancel_event=cancel, priority="final")
        with pytest.raises(CancelledError):
            future.result(timeout=2)
    finally:
        worker.stop(timeout=2)


def test_job_cancel_event_aborts_inflight_and_next_job_runs() -> None:
    worker = _worker()
    try:
        cancel = threading.Event()
        blocked = worker.submit_words(
            _samples(1), cancel_event=cancel, deadline=time.monotonic() + 5, priority="final"
        )
        time.sleep(0.1)
        cancel.set()
        with pytest.raises(CancelledError):
            blocked.result(timeout=2)
        recovered = worker.submit_words(_samples(2), priority="final")
        assert [word.word for word in recovered.result(timeout=3)] == [" ok"]
    finally:
        worker.stop(timeout=2)


def test_final_job_survives_global_cancel() -> None:
    worker = _worker()
    try:
        worker.cancel()
        future = worker.submit_words(_samples(2), ignore_global_cancel=True, priority="final")
        assert [word.word for word in future.result(timeout=3)] == [" ok"]
    finally:
        worker.stop(timeout=2)


def test_global_cancel_still_aborts_unflagged_jobs() -> None:
    worker = _worker()
    try:
        worker.cancel()
        future = worker.submit_words(_samples(2), priority="final")
        with pytest.raises(CancelledError):
            future.result(timeout=2)
    finally:
        worker.stop(timeout=2)


def test_ignore_global_cancel_still_honors_cancel_event() -> None:
    worker = _worker()
    try:
        cancel = threading.Event()
        cancel.set()
        future = worker.submit_words(
            _samples(2), cancel_event=cancel, ignore_global_cancel=True, priority="final"
        )
        with pytest.raises(CancelledError):
            future.result(timeout=2)
    finally:
        worker.stop(timeout=2)


def test_submit_after_stop_is_rejected() -> None:
    worker = _worker()
    worker.stop(timeout=2)
    future = worker.submit_words(_samples(2), priority="final")
    with pytest.raises(CancelledError):
        future.result(timeout=2)


class _GrowingRecorder:
    def __init__(self, windows: list[np.ndarray]) -> None:
        self._windows = windows
        self._index = 0

    def snapshot(self, start_seconds: float = 0.0) -> np.ndarray:
        del start_seconds
        window = self._windows[min(self._index, len(self._windows) - 1)]
        self._index += 1
        return window


def test_release_kills_blocked_interim_then_recovers_before_absolute_deadline() -> None:
    cfg = Config.defaults()
    cfg = replace(
        cfg,
        incremental=replace(
            cfg.incremental,
            interim_timeout_seconds=2.0,
            release_timeout_seconds=1.0,
        ),
    )
    worker = ProcessWorker(cfg.asr, child_target=_stub_child)
    worker.start()
    windows = [
        np.full((16000, 1), 2, dtype=np.float32),
        np.full((19200, 1), 2, dtype=np.float32),
        np.full((22400, 1), 1, dtype=np.float32),
    ]
    driver = IncrementalDriver(
        cfg=cfg,
        recorder=_GrowingRecorder(windows),  # type: ignore[arg-type]
        worker=worker,  # type: ignore[arg-type]
        transcriber=StreamingTranscriber(agreement_n=2),
        formatter=HeuristicFormatter(
            cfg.formatting, append_trailing_space=cfg.output.append_trailing_space
        ),
        abort=threading.Event(),
    )
    try:
        assert driver._step()
        assert driver._step()
        driver.signal_partial()
        results = []
        thread = threading.Thread(target=lambda: results.append(driver.run()))
        thread.start()
        time.sleep(0.1)

        released = time.monotonic()
        driver.signal_final(np.full((24000, 1), 1, dtype=np.float32))
        thread.join(timeout=1.3)

        assert not thread.is_alive()
        assert time.monotonic() - released <= 1.2
        assert results == ["Ok "]
        assert results[0].degraded
        assert results[0].recovery_reason == "timeout"
    finally:
        worker.stop(timeout=2)
