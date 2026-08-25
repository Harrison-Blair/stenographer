# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the ASR worker.

Real, non-mocked process lifecycle: a genuinely spawned child loads the model
through a load-only warm-up and decodes a bundled 16 kHz WAV. Covers warm-up
ordering, transcribe-through-child (word timestamps survive IPC), recording-held
idle eviction, idle-kill + transparent restart, and restart after an unexpected
child death. Nothing is mocked — the child is a real process doing real IPC; the
idle/crash tests read the private ``worker._process`` handle only to observe or
kill the real child, an honest in-repo stand-in for external death, not a
subprocess mock. Shutdown cancellation suspends a real child to prove a stalled
decode cannot hold the daemon open indefinitely.

Collected only with STENOGRAPHER_INTEGRATION=1, and skipped further unless the
model is cached locally and the fixture WAV is present, so the default unit run
never spawns a process, loads the model, or touches the network.
"""

from __future__ import annotations

import dataclasses
import io
import os
import pathlib
import signal
import threading
import time

import pytest

pytestmark = pytest.mark.integration

_FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
_CLIP = _FIXTURES / "speech_16k.wav"
_MODEL_ID = "Systran/faster-whisper-medium.en"

if not _CLIP.exists():
    pytest.skip(f"fixture WAV absent: {_CLIP}", allow_module_level=True)

from huggingface_hub import try_to_load_from_cache  # noqa: E402

if try_to_load_from_cache(_MODEL_ID, "config.json") is None:
    pytest.skip(f"model not cached: {_MODEL_ID}", allow_module_level=True)

import soundfile  # noqa: E402

from stenographer.config import Config  # noqa: E402
from stenographer.transcribe import worker as worker_module  # noqa: E402
from stenographer.transcribe.worker import Worker, WorkerError  # noqa: E402
from stenographer.utils.logging_setup import setup_logging, shutdown_logging  # noqa: E402


def _read(path: pathlib.Path):
    return soundfile.read(str(path), dtype="float32", always_2d=True)[0]


def test_transcribe_through_child_matches_in_process():
    from stenographer.transcribe import model as v2model

    samples = _read(_CLIP)
    cfg = Config.defaults()

    in_process = v2model.Model(cfg.asr)
    try:
        expected = in_process.transcribe(samples)
    finally:
        in_process.close()

    worker = Worker(cfg.asr)
    try:
        result = worker.transcribe(samples)
    finally:
        worker.shutdown()

    assert result.text.strip() == expected.text.strip()
    assert result.text.strip() != ""
    # Word timestamps must survive the spawn/pickle round trip.
    assert any(seg.words for seg in result.segments)


def test_warmup_loads_before_first_decode_and_lifecycle_is_ordered():
    samples = _read(_CLIP)
    cfg = Config.defaults()

    events: list[str] = []
    worker = Worker(
        cfg.asr,
        on_model_loading=lambda: events.append("loading"),
        on_model_ready=lambda: events.append("ready"),
        on_model_loading_finished=lambda: events.append("loading_finished"),
        on_transcribing=lambda: events.append("transcribing"),
    )
    try:
        worker.warmup()
        assert events == ["loading", "ready", "loading_finished"]

        worker.transcribe(samples)
        assert events == ["loading", "ready", "loading_finished", "transcribing"]

        worker.transcribe(samples)
        assert events == [
            "loading",
            "ready",
            "loading_finished",
            "transcribing",
            "transcribing",
        ]
    finally:
        worker.shutdown()


def test_failed_real_model_load_still_reports_loading_finished():
    base = Config.defaults()
    cfg = dataclasses.replace(base.asr, model="invalid/nonexistent-stenographer-smoke-model")
    events: list[str] = []
    worker = Worker(
        cfg,
        on_model_loading=lambda: events.append("loading"),
        on_model_ready=lambda: events.append("ready"),
        on_model_loading_finished=lambda: events.append("loading_finished"),
    )
    try:
        with pytest.raises(WorkerError):
            worker.warmup()
        assert events == ["loading", "loading_finished"]
    finally:
        worker.shutdown()


def test_idle_kill_then_restart():
    samples = _read(_CLIP)
    base = Config.defaults()
    cfg = dataclasses.replace(base.asr, idle_unload_seconds=1)

    calls: list[int] = []
    worker = Worker(cfg, on_model_loading=lambda: calls.append(1))
    try:
        worker.hold_model()
        worker.warmup()
        assert worker.is_alive()
        assert len(calls) == 1

        # A recording-scoped hold keeps a warmed model alive even when the
        # configured idle timeout is shorter than the recording itself.
        time.sleep(1.5)
        assert worker.is_alive()
        worker.release_model()

        # The lock-guarded idle timer must terminate the child within idle+grace.
        deadline = time.monotonic() + 5.0
        while worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not worker.is_alive()

        # The next request transparently respawns and loading activity returns.
        result = worker.transcribe(samples)
        assert worker.is_alive()
        assert len(calls) == 2
        assert result.text.strip() != ""
    finally:
        worker.shutdown()


def test_restart_after_forced_child_death():
    samples = _read(_CLIP)
    cfg = Config.defaults()

    worker = Worker(cfg.asr)
    try:
        worker.transcribe(samples)
        assert worker.is_alive()

        # Simulate an unexpected native crash by killing the real child.
        worker._process.kill()
        worker._process.join()
        assert not worker.is_alive()

        # restart-if-dead: the next request respawns and succeeds; the daemon
        # side never went down.
        result = worker.transcribe(samples)
        assert worker.is_alive()
        assert result.text.strip() != ""
    finally:
        worker.shutdown()


def test_decode_timeout_reaps_suspended_child_then_respawns(monkeypatch):
    samples = _read(_CLIP)
    worker = Worker(Config.defaults().asr)
    try:
        worker.warmup()
        proc = worker._process
        assert proc is not None and proc.is_alive()
        os.kill(proc.pid, signal.SIGSTOP)

        # Exercise the production deadline/teardown path against a real child
        # without waiting for the fixed 60-second floor or two-second join.
        with monkeypatch.context() as shortened:
            shortened.setattr(worker_module, "_POLL_SECONDS", 0.01)
            shortened.setattr(worker_module, "_JOIN_SECONDS", 0.25)
            shortened.setattr(worker_module, "_DECODE_MIN_TIMEOUT_SECONDS", 0.25)
            shortened.setattr(worker_module, "_DECODE_REALTIME_MULTIPLIER", 0.0)
            with pytest.raises(WorkerError, match="timed out during transcribe"):
                worker.transcribe(samples)

        assert not worker.is_alive()
        assert worker._process is None
        assert worker._request_q is None
        assert worker._response_q is None
        assert worker._log_q is None
        assert worker._log_listener is None
        assert not worker.is_model_ready

        # A timeout poisons only that child's protocol. The next request uses a
        # fresh process under the production deadline and decodes normally.
        result = worker.transcribe(samples)
        assert worker.is_alive()
        assert worker._process is not proc
        assert result.text.strip() != ""
    finally:
        worker.shutdown()


def test_shutdown_terminates_suspended_inflight_decode():
    samples = _read(_CLIP)
    worker = Worker(Config.defaults().asr)
    errors: list[Exception] = []

    def transcribe() -> None:
        try:
            worker.transcribe(samples)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=transcribe, name="worker-shutdown-smoke")
    thread.start()
    try:
        deadline = time.monotonic() + 10.0
        while (
            worker._process is None or not worker._process.is_alive()
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        proc = worker._process
        assert proc is not None and proc.is_alive()

        # Suspend the real child so native inference cannot complete and only
        # the shutdown cancellation path can release the transcription thread.
        os.kill(proc.pid, signal.SIGSTOP)
        started = time.monotonic()
        worker.shutdown()
        elapsed = time.monotonic() - started

        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert elapsed < 5.0
        assert len(errors) == 1
        assert isinstance(errors[0], WorkerError)
        assert "shut down" in str(errors[0])
        assert not worker.is_alive()
        with pytest.raises(WorkerError, match="shut down"):
            worker.transcribe(samples)
    finally:
        worker.shutdown()
        thread.join(timeout=5.0)


def test_spawned_worker_forwards_private_safe_decode_metrics(tmp_path):
    samples = _read(_CLIP)
    cfg = Config.defaults()
    stderr = io.StringIO()
    shutdown_logging()
    setup_logging(env={"XDG_STATE_HOME": str(tmp_path)}, home=tmp_path, stderr=stderr)

    worker = Worker(cfg.asr)
    try:
        result = worker.transcribe(samples)
    finally:
        worker.shutdown()
        shutdown_logging()

    records = stderr.getvalue()
    assert "asr: model_loaded elapsed_ms=" in records
    assert "asr: decode_complete elapsed_ms=" in records
    assert f"transcript_chars={len(result.text)}" in records
    assert result.text.strip()
    assert result.text.strip() not in records
