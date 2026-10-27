# SPDX-License-Identifier: GPL-3.0-or-later
"""File job queue behavior at media and ASR process boundaries."""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import shutil
import threading
import time
from datetime import UTC, datetime

import numpy as np
import pytest
import soundfile

from stenographer.lib.config.models import Config
from stenographer.lib.files.engine import FilesEngine
from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder
from stenographer.lib.transcribe.results import TranscriptionResult


class FakeAsrProcess:
    def __init__(self, *, started=None, release=None):
        self.pid = 713
        self.exit_code = None
        self.running = True
        self.sent = []
        self.results = queue.Queue()
        self.started = started
        self.release = release
        self.decode_count = 0

    def is_running(self):
        return self.running

    def send(self, message):
        self.sent.append(message)
        if message[0] == "load":
            self.results.put(("model_ready",))
        elif message[0] == "job":
            self.decode_count += 1
            if self.started is not None and self.decode_count == 1:
                self.started.set()
                assert self.release.wait(5)
            self.results.put(
                (
                    "ok",
                    TranscriptionResult(
                        text=f"recognized phrase {self.decode_count}",
                        duration_seconds=1.0,
                    ),
                )
            )

    def receive(self, timeout):
        try:
            return self.results.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def close(self, graceful=False):
        self.running = False


class FakeAsrTransport:
    def __init__(self, process):
        self.process = process
        self.spawned = []

    def spawn(self, _config, *, on_log):
        self.spawned.append(self.process)
        return self.process


class FakeSegmenter:
    def __init__(self):
        self.samples = np.empty(0, dtype=np.float32)

    def accept(self, samples):
        self.samples = np.concatenate((self.samples, samples))
        if self.samples.size < 32000:
            return []
        return self._phrases()

    def flush(self):
        return self._phrases() if self.samples.size else []

    def _phrases(self):
        samples, self.samples = self.samples, np.empty(0, dtype=np.float32)
        midpoint = samples.size // 2
        return [
            _phrase(0.0, 1.0, samples[:midpoint]),
            _phrase(1.0, 2.0, samples[midpoint:]),
        ]


def _phrase(start, end, samples):
    from stenographer.lib.live.phrase import Phrase

    return Phrase("system", start, end, samples)


def _audio(path):
    soundfile.write(path, np.full(32000, 0.1, dtype=np.float32), 16000)
    return path


def _wait_for(job, state):
    deadline = time.monotonic() + 5
    while job.state != state and time.monotonic() < deadline:
        time.sleep(0.005)
    assert job.state == state


_JOB_START = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)


def _engine(tmp_path, process, **kwargs):
    kwargs.setdefault("clock", lambda: _JOB_START)
    return FilesEngine(
        Config.defaults(),
        data_dir=tmp_path / "data",
        decoder=SubprocessFfmpegDecoder(),
        transport=FakeAsrTransport(process),
        segmenter_factory=FakeSegmenter,
        **kwargs,
    )


def _sessions(tmp_path):
    return tmp_path / "data" / "sessions"


def _transcript_rows(directory, name="transcript.jsonl"):
    return [json.loads(row) for row in (directory / name).read_text(encoding="utf-8").splitlines()]


def test_file_job_writes_phrase_text_to_a_new_file_session_and_progress_preview(tmp_path):
    process = FakeAsrProcess()
    engine = _engine(tmp_path, process)
    source = _audio(tmp_path / "Meeting Notes.WAV")
    job = engine.submit(source, diarize=False)
    try:
        assert job.wait(5) == "completed"
        assert job.session_id == "20260302T040506Z"
        session = _sessions(tmp_path) / job.session_id
        assert sorted(path.name for path in session.iterdir()) == [
            "session.json",
            "source.wav",
            "transcript.jsonl",
            "transcript.md",
        ]
        assert session.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in session.iterdir())
        assert (session / "source.wav").read_bytes() == source.read_bytes()
        assert json.loads((session / "session.json").read_text(encoding="utf-8")) == {
            "current_revision": "transcript.jsonl",
            "duration_seconds": 2.0,
            "kind": "file",
            "source_file": "source.wav",
            "source_name": "Meeting Notes.WAV",
        }
        assert [
            (row["source"], row["speaker_id"], row["text"]) for row in _transcript_rows(session)
        ] == [
            ("file", "speaker-1", "recognized phrase 1"),
            ("file", "speaker-1", "recognized phrase 2"),
        ]
        assert "**Speaker 1:** recognized phrase 1" in (session / "transcript.md").read_text(
            encoding="utf-8"
        )
        assert not (tmp_path / "data" / "files").exists()
        assert len(job.progress.completed_lines) == 2
        assert job.progress.stage == "save"
        assert job.progress.percent == 100
        assert process.sent[0][0] == "load"
        assert [message[0] for message in process.sent[1:]] == ["job", "job"]
    finally:
        engine.close()


def test_file_session_name_adds_one_second_while_the_name_exists(tmp_path):
    for name in ("20260302T040506Z", "20260302T040507Z"):
        (_sessions(tmp_path) / name).mkdir(parents=True)
    engine = _engine(tmp_path, FakeAsrProcess())
    job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        assert job.wait(5) == "completed"
        assert job.session_id == "20260302T040508Z"
        assert sorted(path.name for path in _sessions(tmp_path).iterdir()) == [
            "20260302T040506Z",
            "20260302T040507Z",
            "20260302T040508Z",
        ]
        assert list((_sessions(tmp_path) / "20260302T040506Z").iterdir()) == []
    finally:
        engine.close()


def test_cancel_finishes_current_phrase_without_saving_output(tmp_path):
    started = threading.Event()
    release = threading.Event()
    process = FakeAsrProcess(started=started, release=release)
    engine = _engine(tmp_path, process)
    job = engine.submit(_audio(tmp_path / "cancel.wav"), diarize=False)
    progress_events = []
    job.subscribe(progress_events.append)
    try:
        assert started.wait(5)
        assert job.cancel()
        release.set()
        assert job.wait(5) == "cancelled"
        assert process.decode_count == 1
        assert any(event.stage == "transcribe" for event in progress_events)
        assert job.session_id is None
        assert not _sessions(tmp_path).exists() or not any(_sessions(tmp_path).iterdir())
    finally:
        release.set()
        engine.close()


def test_jobs_run_in_fifo_order(tmp_path):
    started = threading.Event()
    release = threading.Event()
    process = FakeAsrProcess(started=started, release=release)
    engine = _engine(tmp_path, process)
    first = engine.submit(_audio(tmp_path / "first.wav"), diarize=False)
    try:
        assert started.wait(5)
        second = engine.submit(_audio(tmp_path / "second.wav"), diarize=False)
        assert first.state == "running"
        assert second.state == "queued"
        release.set()
        assert first.wait(5) == "completed"
        assert second.wait(5) == "completed"
        assert first.started_at <= second.started_at
        assert second.session_id == "20260302T040507Z"
        assert "recognized phrase 3" in (
            _sessions(tmp_path) / second.session_id / "transcript.md"
        ).read_text(encoding="utf-8")
    finally:
        release.set()
        engine.close()


def test_missing_ffmpeg_blocks_an_unsupported_file_before_asr_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    process = FakeAsrProcess()
    engine = _engine(tmp_path, process)
    path = tmp_path / "voice.m4a"
    path.touch()

    try:
        job = engine.submit(path, diarize=False)
        assert job.wait(5) == "needs_ffmpeg"
        assert job.error == "needs ffmpeg"
        assert not process.sent
        assert job.session_id is None
    finally:
        engine.close()


def test_refine_is_opt_in_and_updates_the_preview(tmp_path):
    class Refiner:
        def will_refine(self, text):
            return True

        def refine(self, text, *, cancelled):
            return f"clean {text}"

    process = FakeAsrProcess()
    engine = _engine(tmp_path, process, refiner_factory=lambda _config: Refiner())
    job = engine.submit(
        _audio(tmp_path / "refine.wav"),
        diarize=False,
        refine=True,
    )
    try:
        assert job.wait(5) == "completed"
        assert "clean recognized phrase 1" in (
            _sessions(tmp_path) / job.session_id / "transcript.md"
        ).read_text(encoding="utf-8")
    finally:
        engine.close()


def test_fixed_speaker_count_runs_batch_diarization(tmp_path):
    class SpeakerTracker:
        def __init__(self):
            self.count = 0

        def embed(self, _samples):
            self.count += 1
            return np.array([1.0, 0.0] if self.count == 1 else [0.0, 1.0], dtype=np.float32)

        def assign_embedding(self, _embedding, *, duration):
            return f"speaker-{self.count}"

        def label(self, speaker_id):
            return f"Speaker {speaker_id.removeprefix('speaker-')}"

    started = threading.Event()
    release = threading.Event()
    process = FakeAsrProcess(started=started, release=release)
    engine = _engine(
        tmp_path,
        process,
        speaker_tracker_factory=SpeakerTracker,
    )
    job = engine.submit(
        _audio(tmp_path / "speakers.wav"),
        diarize=True,
        speaker_count=1,
    )
    progress_events = []
    job.subscribe(progress_events.append)
    try:
        assert started.wait(5)
        release.set()
        assert job.wait(5) == "completed"
        assert any(event.stage == "diarize" for event in progress_events)
        assert job.progress.stage == "save"
        assert {line.speaker_id for line in job.progress.completed_lines} == {"speaker-1"}
    finally:
        release.set()
        engine.close()


def test_a_file_job_refine_request_carries_the_vocabulary(tmp_path, ollama_wire):
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults,
        refine=dataclasses.replace(
            defaults.refine, min_words=1, vocabulary=("Kubernetes", "PipeWire")
        ),
    )
    engine = FilesEngine(
        config,
        data_dir=tmp_path / "data",
        decoder=SubprocessFfmpegDecoder(),
        transport=FakeAsrTransport(FakeAsrProcess()),
        segmenter_factory=FakeSegmenter,
    )
    job = engine.submit(_audio(tmp_path / "refine.wav"), diarize=False, refine=True)
    try:
        assert job.wait(5) == "completed"
    finally:
        engine.close()

    assert ollama_wire
    for body in ollama_wire:
        wire = json.dumps(body["messages"])
        assert "Kubernetes" in wire
        assert "PipeWire" in wire


def _snapshot(directory):
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _replace_hook(monkeypatch, name, action):
    original_replace = os.replace

    def hooked(source, destination, *args, **kwargs):
        if os.path.basename(destination) == name:
            action()
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", hooked)


def _raise_injected():
    raise OSError("injected failure")


def _keep_other_folders(tmp_path):
    other = _sessions(tmp_path) / "20250101T000000Z"
    other.mkdir(parents=True)
    (other / "keep.txt").write_text("keep", encoding="utf-8")
    stray = tmp_path / "data" / "files"
    stray.mkdir(parents=True)
    (stray / "old.md").write_text("old", encoding="utf-8")
    return other, stray


def test_failed_file_session_save_removes_only_its_own_folder(tmp_path, monkeypatch):
    other, stray = _keep_other_folders(tmp_path)
    _replace_hook(monkeypatch, "session.json", _raise_injected)
    engine = _engine(tmp_path, FakeAsrProcess())
    job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        assert job.wait(5) == "failed"
        assert job.session_id is None
        assert sorted(path.name for path in _sessions(tmp_path).iterdir()) == [other.name]
        assert (other / "keep.txt").read_text(encoding="utf-8") == "keep"
        assert (stray / "old.md").read_text(encoding="utf-8") == "old"
    finally:
        engine.close()


def test_cancel_during_file_session_save_removes_only_its_own_folder(tmp_path, monkeypatch):
    other, stray = _keep_other_folders(tmp_path)
    holder = {}
    _replace_hook(monkeypatch, "transcript.md", lambda: holder["job"].cancel())
    engine = _engine(tmp_path, FakeAsrProcess())
    holder["job"] = job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        assert job.wait(5) == "cancelled"
        assert job.session_id is None
        assert sorted(path.name for path in _sessions(tmp_path).iterdir()) == [other.name]
        assert (other / "keep.txt").read_text(encoding="utf-8") == "keep"
        assert (stray / "old.md").read_text(encoding="utf-8") == "old"
    finally:
        engine.close()


class RecordingDecoder:
    def __init__(self):
        self.paths = []

    def __call__(self, path):
        from stenographer.lib.files.media import DecodedAudio

        self.paths.append(path)
        return DecodedAudio(np.full(32000, 0.1, dtype=np.float32), 16000, 2.0)


class FakeHubPlatform:
    def __init__(self, data_dir):
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"


@pytest.mark.parametrize(
    ("name", "copied"),
    (
        ("talk", "source.bin"),
        ("talk.verylongext", "source.bin"),
        ("talk.m-4a", "source.bin"),
        ("Talk.MP3", "source.mp3"),
    ),
)
def test_source_name_copy_uses_a_safe_lowercase_suffix(tmp_path, name, copied):
    from stenographer.cli.hub.session_jobs import SessionJobs
    from stenographer.lib.sessions import SessionStore

    source = tmp_path / name
    soundfile.write(source, np.full(32000, 0.1, dtype=np.float32), 16000, format="WAV")
    engine = _engine(tmp_path, FakeAsrProcess())
    job = engine.submit(source, diarize=False)
    try:
        assert job.wait(5) == "completed"
    finally:
        engine.close()
    store = SessionStore(_sessions(tmp_path))
    session = _sessions(tmp_path) / job.session_id
    metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))

    assert metadata["source_file"] == copied
    assert metadata["source_name"] == name
    assert (session / copied).read_bytes() == source.read_bytes()
    assert not store.read(job.session_id).summary.interrupted
    assert store.source_audio(job.session_id) == session / copied

    decoder = RecordingDecoder()

    class Worker:
        def __init__(self, _config, *, transport):
            self.calls = 0

        def transcribe(self, _samples):
            from stenographer.lib.transcribe.results import TranscriptionResult

            self.calls += 1
            return TranscriptionResult(f"again {self.calls}", 1.0)

        def shutdown(self):
            pass

    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakeHubPlatform(tmp_path / "data"),
        worker_factory=Worker,
        media_decoder=decoder,
    )
    assert jobs.retranscribe(job.session_id) == "transcript.r2.jsonl"
    assert decoder.paths == [session / copied]
    assert [line.text for line in store.read(job.session_id).lines] == ["again 1", "again 2"]


def _recording(tmp_path):
    from stenographer.lib.live.session_writer import SessionWriter
    from stenographer.lib.live.transcript_line import TranscriptLine

    writer = SessionWriter.open(tmp_path / "data", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    writer.write_audio("mic", np.full(32000, 0.1, dtype=np.float32))
    writer.write_audio("system", np.full(32000, 0.1, dtype=np.float32))
    writer.append_line(TranscriptLine(0.0, 0.5, "", "system", "speaker-1", "Speaker 1", "alpha"))
    writer.append_line(TranscriptLine(0.2, 0.9, "", "mic", "you", "You", "bravo"))
    writer.append_line(TranscriptLine(1.5, 1.8, "", "system", "speaker-2", "Speaker 2", "charlie"))
    writer.close()
    return writer.path


def _rows(store, session_id):
    return [
        (line.start, line.source, line.speaker_id, line.label, line.text)
        for line in store.read(session_id).lines
    ]


def _file_rows(session, name):
    return [
        (row["start"], row["source"], row["speaker_id"], row["label"], row["text"])
        for row in _transcript_rows(session, name)
    ]


def test_mic_source_job_writes_a_revision_and_keeps_system_lines_and_renames(tmp_path):
    from stenographer.lib.sessions import SessionStore

    session = _recording(tmp_path)
    store = SessionStore(_sessions(tmp_path))
    store.rename_speaker(session.name, "speaker-1", "Alice")
    engine = _engine(tmp_path, FakeAsrProcess())
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        assert job.wait(5) == "completed"
        assert job.session_id == session.name
        assert sorted(path.name for path in _sessions(tmp_path).iterdir()) == [session.name]
        detail = store.read(session.name)
        assert detail.revision == "transcript.r3.jsonl"
        assert detail.summary.label_state == "file-transcribe"
        assert _file_rows(session, "transcript.r3.jsonl") == [
            (0.0, "mic", "mic-file-r3-1", "You", "recognized phrase 1"),
            (0.0, "system", "speaker-1", "Alice", "alpha"),
            (1.0, "mic", "mic-file-r3-1", "You", "recognized phrase 2"),
            (1.5, "system", "speaker-2", "Speaker 2", "charlie"),
        ]

        store.rename_speaker(session.name, "mic-file-r3-1", "Dana")
        assert [(row[2], row[3]) for row in _rows(store, session.name)] == [
            ("mic-file-r3-1", "Dana"),
            ("speaker-1", "Alice"),
            ("mic-file-r3-1", "Dana"),
            ("speaker-2", "Speaker 2"),
        ]

        second = engine.submit(session / "mic.flac", diarize=False)
        assert second.wait(5) == "completed"
        assert store.read(session.name).revision == "transcript.r5.jsonl"
        assert _file_rows(session, "transcript.r5.jsonl") == [
            (0.0, "mic", "mic-file-r5-1", "You", "recognized phrase 3"),
            (0.0, "system", "speaker-1", "Alice", "alpha"),
            (1.0, "mic", "mic-file-r5-1", "You", "recognized phrase 4"),
            (1.5, "system", "speaker-2", "Speaker 2", "charlie"),
        ]
        assert "Dana" not in {row[3] for row in _rows(store, session.name)}
    finally:
        engine.close()


class TwoVoiceTracker:
    def __init__(self):
        self.count = 0

    def embed(self, _samples):
        self.count += 1
        return np.array([1.0, 0.0] if self.count % 2 else [0.0, 1.0], dtype=np.float32)

    def assign_embedding(self, _embedding, *, duration):
        return f"speaker-{self.count}"

    def label(self, speaker_id):
        return f"Speaker {speaker_id.removeprefix('speaker-')}"


@pytest.mark.parametrize(
    ("source", "kept", "new_labels"),
    (
        (
            "system",
            [(0.2, "mic", "you", "You", "bravo")],
            ("Speaker 1", "Speaker 2"),
        ),
        (
            "mic",
            [
                (0.0, "system", "speaker-1", "Speaker 1", "alpha"),
                (1.5, "system", "speaker-2", "Speaker 2", "charlie"),
            ],
            ("Room 1", "Room 2"),
        ),
    ),
)
def test_diarized_source_job_numbers_new_speakers_and_keeps_the_other_source(
    tmp_path, source, kept, new_labels
):
    from stenographer.lib.sessions import SessionStore

    session = _recording(tmp_path)
    store = SessionStore(_sessions(tmp_path))
    engine = _engine(tmp_path, FakeAsrProcess(), speaker_tracker_factory=TwoVoiceTracker)
    try:
        job = engine.submit(session / f"{source}.flac", diarize=True, speaker_count=2)
        assert job.wait(5) == "completed"
    finally:
        engine.close()
    rows = _file_rows(session, "transcript.r2.jsonl")

    assert store.read(session.name).revision == "transcript.r2.jsonl"
    assert [row for row in rows if row[1] != source] == kept
    assert [row for row in rows if row[1] == source] == [
        (0.0, source, f"{source}-file-r2-1", new_labels[0], "recognized phrase 1"),
        (1.0, source, f"{source}-file-r2-2", new_labels[1], "recognized phrase 2"),
    ]


def test_system_source_job_without_diarization_uses_one_speaker(tmp_path):
    from stenographer.lib.sessions import SessionStore

    session = _recording(tmp_path)
    engine = _engine(tmp_path, FakeAsrProcess())
    try:
        job = engine.submit(session / "system.flac", diarize=False)
        assert job.wait(5) == "completed"
    finally:
        engine.close()

    assert _file_rows(session, "transcript.r2.jsonl") == [
        (0.0, "system", "system-file-r2-1", "Speaker 1", "recognized phrase 1"),
        (0.2, "mic", "you", "You", "bravo"),
        (1.0, "system", "system-file-r2-1", "Speaker 1", "recognized phrase 2"),
    ]
    assert SessionStore(_sessions(tmp_path)).read(session.name).revision == "transcript.r2.jsonl"


def test_file_session_source_job_replaces_all_lines(tmp_path):
    from stenographer.lib.sessions import SessionStore

    engine = _engine(tmp_path, FakeAsrProcess())
    try:
        first = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
        assert first.wait(5) == "completed"
        session = _sessions(tmp_path) / first.session_id
        store = SessionStore(_sessions(tmp_path))
        store.rename_speaker(first.session_id, "speaker-1", "Alice")
        again = engine.submit(session / "source.wav", diarize=False)
        assert again.wait(5) == "completed"
    finally:
        engine.close()

    assert again.session_id == first.session_id
    assert [path.name for path in _sessions(tmp_path).iterdir()] == [first.session_id]
    detail = store.read(first.session_id)
    assert detail.revision == "transcript.r3.jsonl"
    assert detail.summary.kind == "file"
    assert [(line.source, line.label, line.text) for line in detail.lines] == [
        ("file", "Speaker 1", "recognized phrase 3"),
        ("file", "Speaker 1", "recognized phrase 4"),
    ]


@pytest.mark.parametrize("layout", ("outside", "symlink", "nested"))
def test_source_paths_that_leave_a_session_folder_make_a_new_session(tmp_path, layout):
    session = _recording(tmp_path)
    before = _snapshot(session)
    outside = tmp_path / "elsewhere" / session.name
    outside.mkdir(parents=True)
    if layout == "outside":
        path = outside / "mic.flac"
        shutil.copyfile(session / "mic.flac", path)
    elif layout == "symlink":
        real = outside / "voice.flac"
        shutil.copyfile(session / "mic.flac", real)
        link_session = _sessions(tmp_path) / "20260101T000000Z"
        link_session.mkdir()
        path = link_session / "mic.flac"
        path.symlink_to(real)
    else:
        nested = session / "nested"
        nested.mkdir()
        path = nested / "mic.flac"
        shutil.copyfile(session / "mic.flac", path)
        before = _snapshot_tree(session)
    engine = _engine(tmp_path, FakeAsrProcess())
    try:
        job = engine.submit(path, diarize=False)
        assert job.wait(5) == "completed"
    finally:
        engine.close()

    assert job.session_id == "20260302T040506Z"
    created = _sessions(tmp_path) / job.session_id
    assert json.loads((created / "session.json").read_text(encoding="utf-8"))["kind"] == "file"
    assert (_snapshot_tree(session) if layout == "nested" else _snapshot(session)) == before


def _snapshot_tree(directory):
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in sorted(directory.rglob("*"))
    }


def test_cancelled_revision_job_leaves_the_session_byte_identical(tmp_path):
    session = _recording(tmp_path)
    before = _snapshot(session)
    started = threading.Event()
    release = threading.Event()
    engine = _engine(tmp_path, FakeAsrProcess(started=started, release=release))
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        assert started.wait(5)
        assert job.cancel()
        release.set()
        assert job.wait(5) == "cancelled"
    finally:
        release.set()
        engine.close()

    assert _snapshot(session) == before
    assert sorted(path.name for path in _sessions(tmp_path).iterdir()) == [session.name]


@pytest.mark.parametrize("step", ("failed", "cancelled"))
def test_revision_job_stopped_while_saving_leaves_the_session_byte_identical(
    tmp_path, monkeypatch, step
):
    session = _recording(tmp_path)
    before = _snapshot(session)
    holder = {}
    if step == "failed":
        _replace_hook(monkeypatch, "session.json", _raise_injected)
    else:
        _replace_hook(monkeypatch, "transcript.r2.md", lambda: holder["job"].cancel())
    engine = _engine(tmp_path, FakeAsrProcess())
    try:
        holder["job"] = job = engine.submit(session / "mic.flac", diarize=False)
        assert job.wait(5) == step
    finally:
        engine.close()
    monkeypatch.undo()

    assert _snapshot(session) == before


def test_revision_job_stale_revision_keeps_a_rename_made_during_the_job(tmp_path):
    from stenographer.lib.sessions import SessionStore

    session = _recording(tmp_path)

    class RenameAfterRead(SessionStore):
        renamed = False

        def read(self, session_id):
            detail = super().read(session_id)
            if not RenameAfterRead.renamed:
                RenameAfterRead.renamed = True
                SessionStore(self.root).rename_speaker(session_id, "speaker-1", "Alice")
            return detail

    engine = _engine(tmp_path, FakeAsrProcess(), session_store=RenameAfterRead(_sessions(tmp_path)))
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        assert job.wait(5) == "failed"
    finally:
        engine.close()

    assert "changed" in job.error
    store = SessionStore(_sessions(tmp_path))
    assert store.read(session.name).revision == "transcript.r2.jsonl"
    assert _rows(store, session.name) == [
        (0.0, "system", "speaker-1", "Alice", "alpha"),
        (0.2, "mic", "you", "You", "bravo"),
        (1.5, "system", "speaker-2", "Speaker 2", "charlie"),
    ]
    assert not (session / "transcript.r3.jsonl").exists()
