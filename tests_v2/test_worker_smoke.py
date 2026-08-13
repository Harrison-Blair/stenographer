# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the reauthored ASR worker (spec §6.3, M3 Verify).

Real, non-mocked process lifecycle: a genuinely spawned child loads the model
and decodes a bundled 16 kHz WAV. Covers transcribe-through-child (word
timestamps survive IPC), idle-kill + transparent restart, and restart after an
unexpected child death. Nothing is mocked — the child is a real process doing
real IPC; the idle/crash tests read the private ``worker._process`` handle only
to observe or kill the real child, an honest in-repo stand-in for external
death, not a subprocess mock.

Self-skips unless STENOGRAPHER_INTEGRATION=1, the model is cached locally, and
the fixture WAV is present, so the default unit run never spawns a process,
loads the model, or touches the network.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import time

import pytest

pytestmark = pytest.mark.integration

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_CLIP = _FIXTURES / "speech_16k.wav"
_MODEL_ID = "Systran/faster-whisper-medium.en"

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

if not _CLIP.exists():
    pytest.skip(f"fixture WAV absent: {_CLIP}", allow_module_level=True)

from huggingface_hub import try_to_load_from_cache  # noqa: E402

if try_to_load_from_cache(_MODEL_ID, "config.json") is None:
    pytest.skip(f"model not cached: {_MODEL_ID}", allow_module_level=True)

import soundfile  # noqa: E402
from stenographer_v2.config import Config  # noqa: E402
from stenographer_v2.worker import Worker  # noqa: E402


def _read(path: pathlib.Path):
    return soundfile.read(str(path), dtype="float32", always_2d=True)[0]


def test_transcribe_through_child_matches_in_process():
    from stenographer_v2 import model as v2model

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
    # Word timestamps must survive the spawn/pickle round trip (§7 door-opener).
    assert any(seg.words for seg in result.segments)


def test_model_loading_cue_fires_on_first_request_only():
    samples = _read(_CLIP)
    cfg = Config.defaults()

    calls: list[int] = []
    worker = Worker(cfg.asr, on_model_loading=lambda: calls.append(1))
    try:
        worker.transcribe(samples)
        assert len(calls) == 1  # fires on the first (cold) request
        worker.transcribe(samples)
        assert len(calls) == 1  # warm request must not re-fire the cue
    finally:
        worker.shutdown()


def test_idle_kill_then_restart():
    samples = _read(_CLIP)
    base = Config.defaults()
    cfg = dataclasses.replace(base.asr, idle_unload_seconds=1)

    calls: list[int] = []
    worker = Worker(cfg, on_model_loading=lambda: calls.append(1))
    try:
        worker.transcribe(samples)
        assert worker.is_alive()
        assert len(calls) == 1

        # The lock-guarded idle timer must terminate the child within idle+grace.
        deadline = time.monotonic() + 5.0
        while worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not worker.is_alive()

        # The next request transparently respawns and the cue fires again.
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
