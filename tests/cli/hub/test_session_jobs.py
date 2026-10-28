# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for saved-session playback and revision jobs."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.session_jobs import SessionJobs
from stenographer.lib.config.models import Config
from stenographer.lib.files.media import DecodedAudio
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.null_process_counters import NullProcessCounters
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionSourceError, StaleRevisionError
from stenographer.lib.transcribe.results import TranscriptionResult


class FakePlatform:
    def __init__(self, data_dir):
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"

    def process_counters(self):
        return NullProcessCounters()


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


class VoiceSpeakerTracker:
    """Embed each saved phrase from its start time: two voices alternate."""

    def __init__(self, _model_path):
        self.vectors = iter(
            np.array(vector, dtype=np.float32)
            for vector in ([1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [1.0, 0.0])
        )

    def embed(self, _samples):
        return next(self.vectors)


def _write_room_session(root: Path, *, diarized: bool) -> Path:
    writer = SessionWriter.open(root.parent, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    if diarized:
        writer.mark_mic_diarized()
    writer.write_audio("mic", np.full(16_000 * 12, 0.1, dtype=np.float32))
    writer.write_audio("system", np.full(16_000 * 12, 0.1, dtype=np.float32))
    writer.append_line(
        TranscriptLine(0.0, 2.0, "", "system", "speaker-1", "Speaker 1", "fixture line")
    )
    speaker = ("room-1", "Room 1") if diarized else ("you", "You")
    for start in (2.0, 5.0, 8.0):
        writer.append_line(TranscriptLine(start, start + 2.5, "", "mic", *speaker, "fixture line"))
    writer.close()
    return writer.path


def _jobs(tmp_path, store, tracker):
    model_path = tmp_path / "models" / "live" / LIVE_MODELS[1].filename
    model_path.parent.mkdir(parents=True)
    model_path.touch()
    return SessionJobs(
        store, Config.defaults(), FakePlatform(tmp_path), speaker_tracker_factory=tracker
    )


def test_rediarize_relabels_mic_lines_as_room_speakers_when_the_session_was_diarized(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_room_session(sessions_root, diarized=True)
    store = SessionStore(sessions_root)

    _jobs(tmp_path, store, VoiceSpeakerTracker).rediarize(session.name)

    detail = store.read(session.name)
    assert [(line.source, line.speaker_id, line.label) for line in detail.lines] == [
        ("system", "speaker-1", "Speaker 1"),
        ("mic", "room-1", "Room 1"),
        ("mic", "room-2", "Room 2"),
        ("mic", "room-2", "Room 2"),
    ]
    assert detail.diarize_mic is True


def test_rediarize_leaves_mic_lines_as_you_in_sessions_without_the_flag(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_room_session(sessions_root, diarized=False)
    store = SessionStore(sessions_root)
    embedded = []

    class CountingTracker(VoiceSpeakerTracker):
        def embed(self, samples):
            embedded.append(len(samples))
            return super().embed(samples)

    _jobs(tmp_path, store, CountingTracker).rediarize(session.name)

    detail = store.read(session.name)
    assert [(line.source, line.label) for line in detail.lines] == [
        ("system", "Speaker 1"),
        ("mic", "You"),
        ("mic", "You"),
        ("mic", "You"),
    ]
    assert len(embedded) == 1


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


class RecordingDecoder:
    def __init__(self):
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        return DecodedAudio(np.full(48_000, 0.1, dtype=np.float32), 16_000, 3.0)


def _file_session(sessions_root: Path, tmp_path: Path) -> str:
    source = tmp_path / "Interview.wav"
    sf.write(source, np.full(48_000, 0.1, dtype=np.float32), 16_000)
    return SessionStore(sessions_root).create_file_session(
        source,
        started_at=datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
        duration_seconds=3.0,
        lines=[
            TranscriptLine(0.0, 1.0, "", "file", "speaker-1", "Speaker 1", "alpha"),
            TranscriptLine(1.5, 2.5, "", "file", "speaker-2", "Speaker 2", "bravo"),
        ],
    )


def test_retranscribe_file_session_decodes_its_source_and_saves_a_revision(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _file_session(sessions_root, tmp_path)
    store = SessionStore(sessions_root)
    decoder = RecordingDecoder()
    workers = []

    def make_worker(_asr_config, *, transport):
        workers.append(FakeWorker())
        return workers[-1]

    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path),
        worker_factory=make_worker,
        media_decoder=decoder,
    )

    revision = jobs.retranscribe(session_id)

    detail = store.read(session_id)
    assert revision == "transcript.r2.jsonl"
    assert decoder.paths == [sessions_root / session_id / "source.wav"]
    assert [(line.source, line.label, line.text) for line in detail.lines] == [
        ("file", "Speaker 1", "new phrase 1"),
        ("file", "Speaker 2", "new phrase 2"),
    ]
    assert detail.summary.kind == "file"
    assert workers[0].closed


def test_retranscribe_file_session_refuses_an_invalid_source(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _file_session(sessions_root, tmp_path)
    directory = sessions_root / session_id
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    (directory / "source.wav").unlink()
    (directory / "source.wav").symlink_to(outside)
    decoder = RecordingDecoder()
    jobs = SessionJobs(
        SessionStore(sessions_root),
        Config.defaults(),
        FakePlatform(tmp_path),
        worker_factory=lambda *_args, **_kwargs: FakeWorker(),
        media_decoder=decoder,
    )

    with pytest.raises(SessionSourceError, match="source audio"):
        jobs.retranscribe(session_id)

    assert decoder.paths == []
    assert not (directory / "transcript.r2.jsonl").exists()


def test_rediarize_file_session_raises_a_clear_error(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _file_session(sessions_root, tmp_path)
    store = SessionStore(sessions_root)

    with pytest.raises(ValueError, match="use Re-transcribe"):
        _jobs(tmp_path, store, VoiceSpeakerTracker).rediarize(session_id)

    assert store.read(session_id).revision == "transcript.jsonl"


class RenameAfterRead(SessionStore):
    """Save a rename from another store right after the job reads the session."""

    def __init__(self, root):
        super().__init__(root)
        self.renamed = False

    def read(self, session_id):
        detail = super().read(session_id)
        if not self.renamed:
            self.renamed = True
            SessionStore(self.root).rename_speaker(session_id, "speaker-1", "Alex")
        return detail


@pytest.mark.parametrize("operation", ("retranscribe", "rediarize"))
def test_stale_revision_keeps_a_rename_saved_during_the_job(tmp_path, operation):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    store = RenameAfterRead(sessions_root)
    model_path = tmp_path / "models" / "live" / LIVE_MODELS[1].filename
    model_path.parent.mkdir(parents=True)
    model_path.touch()
    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path),
        speaker_tracker_factory=FakeSpeakerTracker,
        worker_factory=lambda *_args, **_kwargs: FakeWorker(),
    )

    with pytest.raises(StaleRevisionError, match="changed since it was read"):
        getattr(jobs, operation)(session.name)

    detail = SessionStore(sessions_root).read(session.name)
    assert detail.revision == "transcript.r2.jsonl"
    assert [(line.source, line.speaker_id, line.label, line.text) for line in detail.lines] == [
        ("system", "speaker-1", "Alex", "first fixture line"),
        ("mic", "you", "You", "second fixture line"),
    ]
    assert not (session / "transcript.r3.jsonl").exists()
