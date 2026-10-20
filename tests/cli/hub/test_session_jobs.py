# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for saved-session playback and revision jobs."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.session_jobs import SessionJobs
from stenographer.lib.config.models import Config
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.results import TranscriptionResult


class FakePlatform:
    def __init__(self, data_dir):
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"


class FakeSpeakerTracker:
    def __init__(self, _model_path):
        self.embeddings = iter((np.array([1.0, 0.0], dtype=np.float32),))

    def embed(self, _samples):
        return next(self.embeddings)


class FakeWorker:
    def __init__(self):
        self.closed = False
        self.calls = 0

    def transcribe(self, _samples):
        self.calls += 1
        return TranscriptionResult(f"new phrase {self.calls}", 0.8)

    def shutdown(self):
        self.closed = True


class FakePlayer:
    def __init__(self):
        self.pid = 43210
        self.terminated = False
        self.finished = threading.Event()

    def poll(self):
        return 0 if self.finished.is_set() else None

    def terminate(self):
        self.terminated = True
        self.finished.set()

    def wait(self):
        self.finished.wait()
        return 0


def _write_session(root: Path) -> Path:
    writer = SessionWriter.open(root.parent, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    writer.write_audio("mic", np.full(32_000, 0.1, dtype=np.float32))
    writer.write_audio("system", np.full(32_000, 0.1, dtype=np.float32))
    writer.append_line(
        TranscriptLine(0.0, 0.8, "", "system", "speaker-1", "Speaker 1", "first fixture line")
    )
    writer.append_line(TranscriptLine(0.8, 1.6, "", "mic", "you", "You", "second fixture line"))
    writer.close()
    return writer.path


def test_rediarize_uses_task_pass_and_saves_a_renamed_revision(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    store = SessionStore(sessions_root)
    store.rename_speaker(session.name, "speaker-1", "Alex")
    model_path = tmp_path / "models" / "live" / LIVE_MODELS[1].filename
    model_path.parent.mkdir(parents=True)
    model_path.touch()
    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path),
        speaker_tracker_factory=FakeSpeakerTracker,
    )

    revision = jobs.rediarize(session.name)

    detail = store.read(session.name)
    assert revision == "transcript.r3.jsonl"
    assert detail.revision == revision
    assert [(line.source, line.label) for line in detail.lines] == [
        ("system", "Alex"),
        ("mic", "You"),
    ]
    assert (session / "transcript.jsonl").is_file()


def test_retranscribe_uses_current_asr_and_saves_new_text_revision(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    store = SessionStore(sessions_root)
    config = Config.defaults()
    platform = FakePlatform(tmp_path)
    workers = []
    worker_configs = []

    def make_worker(asr_config, *, transport):
        worker_configs.append((asr_config, transport))
        worker = FakeWorker()
        workers.append(worker)
        return worker

    jobs = SessionJobs(store, config, platform, worker_factory=make_worker)
    jobs.update_config(config)

    revision = jobs.retranscribe(session.name)

    detail = store.read(session.name)
    assert revision == "transcript.r2.jsonl"
    assert [line.text for line in detail.lines] == ["new phrase 1", "new phrase 2"]
    assert worker_configs == [(config.asr, "fake-transport")]
    assert workers[0].calls == 2
    assert workers[0].closed
    assert (session / "transcript.jsonl").is_file()


def test_playback_mixes_saved_sources_and_second_press_stops_own_player(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    player = FakePlayer()
    commands = []

    def start_player(command):
        commands.append(command)
        return player

    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(sessions_root),
        player_factory=start_player,
    )

    services.toggle_session_playback(session.name)
    mixed_path = Path(commands[0][1])
    assert services._player_pid == player.pid
    samples, sample_rate = sf.read(mixed_path, dtype="float32")
    services.toggle_session_playback(session.name)

    assert commands[0][0] == "pw-play"
    assert sample_rate == 16_000
    assert samples.size == 32_000
    assert np.allclose(samples, 0.2, atol=0.001)
    assert player.terminated
    assert player.finished.wait(timeout=1)
    deadline = time.monotonic() + 1
    while mixed_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not mixed_path.exists()
