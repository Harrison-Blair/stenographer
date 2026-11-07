# SPDX-License-Identifier: GPL-3.0-or-later
"""File job queue behavior at media and ASR process boundaries."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import threading
from datetime import UTC, datetime

import numpy as np
import pytest
import soundfile

from stenographer.lib.config.models import Config
from stenographer.lib.files import engine as engine_module
from stenographer.lib.files.engine import FilesEngine
from stenographer.lib.live import voice_split
from stenographer.lib.live.errors import SpeechPassError
from stenographer.lib.live.phrase_segmenter import Phrase
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.results import TranscriptionResult
from tests.lib.live.speech_support import level_pieces
from tests.lib.platform.support import NullProcessCounters
from tests.lib.transcribe.support import FakeAsrProcess, FakeAsrTransport
from tests.support import wait_until


@pytest.fixture(autouse=True)
def _level_pieces(monkeypatch):
    monkeypatch.setattr(voice_split, "find_speech_pieces", level_pieces)


def _file_asr_process(*, started=None, release=None):
    def reply(process, message):
        if message[0] == "load":
            return ("model_ready",)
        if message[0] == "job":
            process.decode_count += 1
            if started is not None and process.decode_count == 1:
                started.set()
                assert release.wait(5)
            return (
                "ok",
                TranscriptionResult(
                    text=f"recognized phrase {process.decode_count}", duration_seconds=1.0
                ),
            )
        return None

    process = FakeAsrProcess(pid=713, reply=reply)
    process.decode_count = 0
    return process


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
    return Phrase("system", start, end, samples)


def _audio(path):
    soundfile.write(path, np.full(32000, 0.1, dtype=np.float32), 16000)
    return path


def _wait_for(job, state):
    assert wait_until(lambda: job.state == state, timeout=5)


_JOB_START = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)


class FakeFilesPlatform:
    def __init__(self, data_dir, process):
        self._data_dir = data_dir
        self._process = process

    def data_dir(self, _env, _home):
        return self._data_dir

    def ffmpeg_decoder(self):
        return SubprocessFfmpegDecoder()

    def asr_transport(self):
        return FakeAsrTransport(self._process)


def _engine(tmp_path, process, **kwargs):
    kwargs.setdefault("clock", lambda: _JOB_START)
    return FilesEngine(
        Config.defaults(),
        platform=FakeFilesPlatform(tmp_path / "data", process),
        segmenter_factory=FakeSegmenter,
        **kwargs,
    )


def _sessions(tmp_path):
    return tmp_path / "data" / "sessions"


def _transcript_rows(directory, name="transcript.jsonl"):
    return [json.loads(row) for row in (directory / name).read_text(encoding="utf-8").splitlines()]


def test_file_job_writes_phrase_text_to_a_new_file_session_and_progress_preview(tmp_path):
    process = _file_asr_process()
    engine = _engine(tmp_path, process)
    source = _audio(tmp_path / "Meeting Notes.WAV")
    job = engine.submit(source, diarize=False)
    try:
        _wait_for(job, "completed")
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


def _transcribe_percents(tmp_path, segmenter):
    """Run a 20 s file through *segmenter*; return each change of transcribe progress."""
    subscribed = threading.Event()

    def segmenter_factory():
        assert subscribed.wait(5)
        return segmenter

    source = tmp_path / "long.wav"
    soundfile.write(source, np.zeros(320000, dtype=np.float32), 16000)
    engine = FilesEngine(
        Config.defaults(),
        platform=FakeFilesPlatform(tmp_path / "data", _file_asr_process()),
        segmenter_factory=segmenter_factory,
        clock=lambda: _JOB_START,
    )
    job = engine.submit(source, diarize=False)
    events = []
    job.subscribe(events.append)
    subscribed.set()
    try:
        _wait_for(job, "completed")
    finally:
        engine.close()
    percents = [event.percent for event in events if event.stage == "transcribe"]
    return [p for index, p in enumerate(percents) if index == 0 or p != percents[index - 1]]


def test_transcribe_progress_advances_through_audio_with_no_phrases(tmp_path):
    class SilentSegmenter:
        def accept(self, _samples):
            return []

        def flush(self):
            return []

    # 65536-frame blocks of 320000 frames, scaled to the 80% that transcription holds.
    assert _transcribe_percents(tmp_path, SilentSegmenter()) == [0, 16, 33, 49, 66, 80]


def test_transcribe_progress_does_not_fall_when_a_phrase_ends_behind_the_audio_read(tmp_path):
    class LateSegmenter:
        def __init__(self):
            self.accepted = 0

        def accept(self, samples):
            self.accepted += 1
            return [_phrase(0.0, 1.0, samples)] if self.accepted == 4 else []

        def flush(self):
            return []

    assert _transcribe_percents(tmp_path, LateSegmenter()) == [0, 16, 33, 49, 66, 80]


def test_file_session_name_adds_one_second_while_the_name_exists(tmp_path):
    for name in ("20260302T040506Z", "20260302T040507Z"):
        (_sessions(tmp_path) / name).mkdir(parents=True)
    engine = _engine(tmp_path, _file_asr_process())
    job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        _wait_for(job, "completed")
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
    process = _file_asr_process(started=started, release=release)
    engine = _engine(tmp_path, process)
    job = engine.submit(_audio(tmp_path / "cancel.wav"), diarize=False)
    progress_events = []
    job.subscribe(progress_events.append)
    try:
        assert started.wait(5)
        assert job.cancel()
        release.set()
        _wait_for(job, "cancelled")
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
    process = _file_asr_process(started=started, release=release)
    engine = _engine(tmp_path, process)
    first = engine.submit(_audio(tmp_path / "first.wav"), diarize=False)
    try:
        assert started.wait(5)
        second = engine.submit(_audio(tmp_path / "second.wav"), diarize=False)
        assert first.state == "running"
        assert second.state == "queued"
        release.set()
        _wait_for(first, "completed")
        _wait_for(second, "completed")
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
    process = _file_asr_process()
    engine = _engine(tmp_path, process)
    path = tmp_path / "voice.m4a"
    path.touch()

    try:
        job = engine.submit(path, diarize=False)
        _wait_for(job, "needs_ffmpeg")
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

    process = _file_asr_process()
    engine = _engine(tmp_path, process, refiner_factory=lambda _config: Refiner())
    job = engine.submit(
        _audio(tmp_path / "refine.wav"),
        diarize=False,
        refine=True,
    )
    try:
        _wait_for(job, "completed")
        assert "clean recognized phrase 1" in (
            _sessions(tmp_path) / job.session_id / "transcript.md"
        ).read_text(encoding="utf-8")
    finally:
        engine.close()


def test_fixed_speaker_count_runs_batch_diarization(tmp_path):
    started = threading.Event()
    release = threading.Event()
    process = _file_asr_process(started=started, release=release)
    engine = _engine(tmp_path, process, speaker_tracker_factory=TwoVoiceTracker)
    job = engine.submit(_audio(tmp_path / "speakers.wav"), diarize=True, speaker_count=1)
    progress_events = []
    job.subscribe(progress_events.append)
    try:
        assert started.wait(5)
        release.set()
        _wait_for(job, "completed")
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
        platform=FakeFilesPlatform(tmp_path / "data", _file_asr_process()),
        segmenter_factory=FakeSegmenter,
    )
    job = engine.submit(_audio(tmp_path / "refine.wav"), diarize=False, refine=True)
    try:
        _wait_for(job, "completed")
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


@pytest.mark.parametrize("step", ("failed", "cancelled"))
def test_stopped_file_session_save_removes_only_its_own_folder(tmp_path, monkeypatch, step):
    other, stray = _keep_other_folders(tmp_path)
    holder = {}
    if step == "failed":
        _replace_hook(monkeypatch, "session.json", _raise_injected)
    else:
        _replace_hook(monkeypatch, "transcript.md", lambda: holder["job"].cancel())
    engine = _engine(tmp_path, _file_asr_process())
    holder["job"] = job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        _wait_for(job, step)
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
        self.paths.append(path)
        yield np.full(32000, 0.1, dtype=np.float32)


class FakeHubPlatform:
    def __init__(self, data_dir):
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"

    def process_counters(self):
        return NullProcessCounters()


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
    from stenographer.lib.sessions.jobs import SessionJobs

    source = tmp_path / name
    soundfile.write(source, np.full(32000, 0.1, dtype=np.float32), 16000, format="WAV")
    engine = _engine(tmp_path, _file_asr_process())
    job = engine.submit(source, diarize=False)
    try:
        _wait_for(job, "completed")
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

    session = _recording(tmp_path)
    store = SessionStore(_sessions(tmp_path))
    store.rename_speaker(session.name, "speaker-1", "Alice")
    engine = _engine(tmp_path, _file_asr_process())
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        _wait_for(job, "completed")
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
        _wait_for(second, "completed")
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
    tmp_path, monkeypatch, source, kept, new_labels
):
    # No speech found, so the two whole lines group as two speakers.
    monkeypatch.setattr(voice_split, "find_speech_pieces", lambda *_args, **_options: ())
    session = _recording(tmp_path)
    store = SessionStore(_sessions(tmp_path))
    engine = _engine(tmp_path, _file_asr_process(), speaker_tracker_factory=TwoVoiceTracker)
    try:
        job = engine.submit(session / f"{source}.flac", diarize=True, speaker_count=2)
        _wait_for(job, "completed")
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

    session = _recording(tmp_path)
    engine = _engine(tmp_path, _file_asr_process())
    try:
        job = engine.submit(session / "system.flac", diarize=False)
        _wait_for(job, "completed")
    finally:
        engine.close()

    assert _file_rows(session, "transcript.r2.jsonl") == [
        (0.0, "system", "system-file-r2-1", "Speaker 1", "recognized phrase 1"),
        (0.2, "mic", "you", "You", "bravo"),
        (1.0, "system", "system-file-r2-1", "Speaker 1", "recognized phrase 2"),
    ]
    assert SessionStore(_sessions(tmp_path)).read(session.name).revision == "transcript.r2.jsonl"


def test_file_session_source_job_replaces_all_lines(tmp_path):

    engine = _engine(tmp_path, _file_asr_process())
    try:
        first = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
        _wait_for(first, "completed")
        session = _sessions(tmp_path) / first.session_id
        store = SessionStore(_sessions(tmp_path))
        store.rename_speaker(first.session_id, "speaker-1", "Alice")
        again = engine.submit(session / "source.wav", diarize=False)
        _wait_for(again, "completed")
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
    engine = _engine(tmp_path, _file_asr_process())
    try:
        job = engine.submit(path, diarize=False)
        _wait_for(job, "completed")
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
    engine = _engine(tmp_path, _file_asr_process(started=started, release=release))
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        assert started.wait(5)
        assert job.cancel()
        release.set()
        _wait_for(job, "cancelled")
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
    engine = _engine(tmp_path, _file_asr_process())
    try:
        holder["job"] = job = engine.submit(session / "mic.flac", diarize=False)
        _wait_for(job, step)
    finally:
        engine.close()
    monkeypatch.undo()

    assert _snapshot(session) == before


def test_revision_job_stale_revision_keeps_a_rename_made_during_the_job(tmp_path):

    session = _recording(tmp_path)

    class RenameAfterRead(SessionStore):
        renamed = False

        def read(self, session_id):
            detail = super().read(session_id)
            if not RenameAfterRead.renamed:
                RenameAfterRead.renamed = True
                SessionStore(self.root).rename_speaker(session_id, "speaker-1", "Alice")
            return detail

    engine = _engine(
        tmp_path, _file_asr_process(), session_store=RenameAfterRead(_sessions(tmp_path))
    )
    try:
        job = engine.submit(session / "mic.flac", diarize=False)
        _wait_for(job, "failed")
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


def test_engine_exposes_its_worker_pids_and_idle_unload_deadline(tmp_path):
    process = _file_asr_process()
    engine = _engine(tmp_path, process)
    try:
        assert engine.process_ids == ()
        assert engine.idle_unload_deadline is None
        job = engine.submit(_audio(tmp_path / "voice.wav"), diarize=False)
        _wait_for(job, "completed")

        assert engine.process_ids == (713,)
        assert engine.idle_unload_deadline is not None
    finally:
        engine.close()
    assert engine.process_ids == ()
    assert engine.idle_unload_deadline is None


def test_missing_vad_model_reports_download_command(tmp_path):
    engine = FilesEngine(
        Config.defaults(), platform=FakeFilesPlatform(tmp_path / "data", _file_asr_process())
    )
    job = engine.submit(_audio(tmp_path / "talk.wav"), diarize=False)
    try:
        _wait_for(job, "failed")
        assert "stenographer model download --live" in job.error
    finally:
        engine.close()


class VoiceChangeSegmenter:
    """Cut 64 s of audio into two 20 s turns and one 24 s phrase with a voice change."""

    def accept(self, _samples):
        return []

    def flush(self):
        audio = _voice_change_samples()
        edges = ((0, 20), (20, 40), (40, 64))
        return [_phrase(a, b, audio[a * 16000 : b * 16000]) for a, b in edges]


def _voice_change_samples():
    return np.concatenate(
        (
            np.full(20 * 16000, 0.1, np.float32),
            np.full(20 * 16000, 0.4, np.float32),
            np.full(204000, 0.1, np.float32),
            np.full(180000, 0.4, np.float32),
        )
    )


class LevelTracker:
    def embed(self, samples):
        low = abs(float(np.median(samples)) - 0.1) < 0.05
        return np.array([1.0, 0.0] if low else [0.0, 1.0], dtype=np.float32)

    def assign_embedding(self, _embedding, *, duration):
        assert duration > 0
        return "speaker-1"

    def label(self, _speaker_id):
        return "Speaker 1"


def _voice_change_job(tmp_path, process=None, **options):
    process = process or _file_asr_process()
    engine = _engine(
        tmp_path,
        process,
        speaker_tracker_factory=LevelTracker,
        **options.pop("engine", {}),
    )
    engine._segmenter_factory = VoiceChangeSegmenter
    source = tmp_path / "meeting.wav"
    soundfile.write(source, _voice_change_samples(), 16000)
    return engine, engine.submit(source, **options)


def test_a_file_job_splits_a_voice_change_at_the_end_of_the_job(tmp_path):
    process = _file_asr_process()
    engine, job = _voice_change_job(tmp_path, process, diarize=True)
    percents = []
    job.subscribe(lambda progress: percents.append(progress.percent))
    try:
        _wait_for(job, "completed")
        lines = job.progress.completed_lines
        assert [line.speaker_id for line in lines] == [
            "speaker-1",
            "speaker-2",
            "speaker-1",
            "speaker-2",
        ]
        assert [line.text for line in lines] == [
            "recognized phrase 1",
            "recognized phrase 2",
            "recognized phrase 4",
            "recognized phrase 5",
        ]
        assert (lines[2].start, lines[3].end) == (40.0, 64.0)
        assert lines[2].end == lines[3].start
        assert 52.0 <= lines[3].start <= 53.5
        assert {line.wall for line in lines} == {""}
        assert percents == sorted(percents)
        rows = _transcript_rows(_sessions(tmp_path) / job.session_id)
        assert len(rows) == 4
    finally:
        engine.close()


def test_a_failed_speaker_pass_saves_the_lines_with_their_tracker_labels(tmp_path, monkeypatch):
    def fail(*_args, **_options):
        raise SpeechPassError("speech pass ended with exit code -9")

    monkeypatch.setattr(voice_split, "find_speech_pieces", fail)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    try:
        _wait_for(job, "completed")
        lines = job.progress.completed_lines
        assert [(line.speaker_id, line.label) for line in lines] == [("speaker-1", "Speaker 1")] * 3
        assert [line.text for line in lines] == [
            "recognized phrase 1",
            "recognized phrase 2",
            "recognized phrase 3",
        ]
        assert len(_transcript_rows(_sessions(tmp_path) / job.session_id)) == 3
    finally:
        engine.close()


def test_a_file_job_percent_never_falls_when_the_pass_finds_no_speech(tmp_path, monkeypatch):
    def no_speech(_samples, _model, *, progress, should_cancel):
        assert not should_cancel()
        progress(1.0)
        return ()

    monkeypatch.setattr(voice_split, "find_speech_pieces", no_speech)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    percents = []
    job.subscribe(lambda progress: percents.append(progress.percent))
    try:
        _wait_for(job, "completed")
        assert percents == sorted(percents)
    finally:
        engine.close()


def test_a_file_job_percent_never_falls_when_the_pass_fails(tmp_path, monkeypatch):
    def fail(_samples, _model, *, progress, should_cancel):
        assert not should_cancel()
        progress(1.0)
        raise SpeechPassError("speech pass ended with exit code -9")

    monkeypatch.setattr(voice_split, "find_speech_pieces", fail)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    percents = []
    job.subscribe(lambda progress: percents.append(progress.percent))
    try:
        _wait_for(job, "completed")
        assert percents == sorted(percents)
    finally:
        engine.close()


def _failing_pass(*_args, **_options):
    raise SpeechPassError("speech pass ended with exit code -9")


def _session_json(tmp_path, session_id):
    return json.loads((_sessions(tmp_path) / session_id / "session.json").read_text())


def test_a_new_file_with_a_failed_pass_is_marked_in_its_session_file(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_split, "find_speech_pieces", _failing_pass)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    try:
        _wait_for(job, "completed")
    finally:
        engine.close()
    assert _session_json(tmp_path, job.session_id)["speaker_pass_failed"] is True
    summary = SessionStore(_sessions(tmp_path)).read(job.session_id).summary
    assert (summary.kind, summary.speaker_pass_failed) == ("file", True)


def test_a_new_file_with_a_passing_pass_has_no_mark(tmp_path):
    engine, job = _voice_change_job(tmp_path, diarize=True)
    try:
        _wait_for(job, "completed")
    finally:
        engine.close()
    assert "speaker_pass_failed" not in _session_json(tmp_path, job.session_id)
    assert not SessionStore(_sessions(tmp_path)).read(job.session_id).summary.speaker_pass_failed


def test_a_new_file_without_speaker_separation_has_no_mark(tmp_path):
    engine, job = _voice_change_job(tmp_path, diarize=False)
    try:
        _wait_for(job, "completed")
    finally:
        engine.close()
    assert "speaker_pass_failed" not in _session_json(tmp_path, job.session_id)


@pytest.mark.parametrize(("fails", "state"), ((True, "live"), (False, "file-transcribe")))
def test_a_job_on_a_recording_file_shows_live_only_after_a_failed_pass(
    tmp_path, monkeypatch, fails, state
):
    monkeypatch.setattr(
        voice_split,
        "find_speech_pieces",
        _failing_pass if fails else lambda *_args, **_options: (),
    )
    session = _recording(tmp_path)
    engine = _engine(tmp_path, _file_asr_process(), speaker_tracker_factory=TwoVoiceTracker)
    try:
        job = engine.submit(session / "system.flac", diarize=True)
        _wait_for(job, "completed")
    finally:
        engine.close()
    summary = SessionStore(_sessions(tmp_path)).read(session.name).summary
    assert (summary.kind, summary.label_state) == ("rec", state)
    # A recording shows its state in the list, so it needs no separate mark.
    assert not summary.speaker_pass_failed


def test_a_job_on_the_source_of_a_file_session_is_marked_after_a_failed_pass(tmp_path, monkeypatch):
    first_engine, first = _voice_change_job(tmp_path, diarize=True)
    try:
        _wait_for(first, "completed")
        session = _sessions(tmp_path) / first.session_id
        monkeypatch.setattr(voice_split, "find_speech_pieces", _failing_pass)
        again = first_engine.submit(session / "source.wav", diarize=True)
        _wait_for(again, "completed")
    finally:
        first_engine.close()
    summary = SessionStore(_sessions(tmp_path)).read(first.session_id).summary
    assert (summary.kind, summary.label_state) == ("file", "live")
    assert summary.speaker_pass_failed


def test_a_speaker_model_error_on_a_piece_saves_the_lines_of_the_job(tmp_path):
    class FailsOnPieces(LevelTracker):
        calls = 0

        def embed(self, samples):
            # The first three embeddings are the phrases of the job.
            type(self).calls += 1
            if self.calls > 3:
                raise RuntimeError("Where node failed")
            return super().embed(samples)

    engine = _engine(tmp_path, _file_asr_process(), speaker_tracker_factory=FailsOnPieces)
    engine._segmenter_factory = VoiceChangeSegmenter
    source = tmp_path / "meeting.wav"
    soundfile.write(source, _voice_change_samples(), 16000)
    job = engine.submit(source, diarize=True)
    try:
        _wait_for(job, "completed")
        assert len(job.progress.completed_lines) == 3
    finally:
        engine.close()


def test_a_cancel_during_a_failed_speaker_pass_stays_a_cancel(tmp_path, monkeypatch):
    def cancel_and_fail(*_args, **_options):
        job.cancel()
        raise SpeechPassError("speech pass ended with exit code -9")

    monkeypatch.setattr(voice_split, "find_speech_pieces", cancel_and_fail)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    try:
        _wait_for(job, "cancelled")
        assert not _sessions(tmp_path).exists() or not list(_sessions(tmp_path).iterdir())
    finally:
        engine.close()


def test_a_file_job_respects_a_set_speaker_count_through_a_split(tmp_path):
    engine, job = _voice_change_job(tmp_path, diarize=True, speaker_count=1)
    try:
        _wait_for(job, "completed")
        # With one speaker set, the phrase has no second voice to split at.
        assert len(job.progress.completed_lines) == 3
        assert {line.speaker_id for line in job.progress.completed_lines} == {"speaker-1"}
    finally:
        engine.close()


def test_a_file_job_keeps_two_set_speakers_after_a_split(tmp_path):
    engine, job = _voice_change_job(tmp_path, diarize=True, speaker_count=2)
    try:
        _wait_for(job, "completed")
        lines = job.progress.completed_lines
        assert len(lines) == 4
        assert {line.speaker_id for line in lines} == {"speaker-1", "speaker-2"}
    finally:
        engine.close()


def test_a_file_job_refines_split_parts(tmp_path):
    class Refiner:
        def will_refine(self, _text):
            return True

        def refine(self, text, *, cancelled):
            assert not cancelled()
            return text.upper()

    engine, job = _voice_change_job(
        tmp_path,
        diarize=True,
        refine=True,
        engine={"refiner_factory": lambda _config: Refiner()},
    )
    try:
        _wait_for(job, "completed")
        assert [line.text for line in job.progress.completed_lines] == [
            "RECOGNIZED PHRASE 1",
            "RECOGNIZED PHRASE 2",
            "RECOGNIZED PHRASE 4",
            "RECOGNIZED PHRASE 5",
        ]
    finally:
        engine.close()


def test_a_cancel_while_a_part_decodes_ends_the_split_with_the_lines_before_it(tmp_path):
    holder = {}

    def reply(process, message):
        if message[0] == "load":
            return ("model_ready",)
        if message[0] == "job":
            process.decode_count += 1
            # Three decodes are the phrases, so the fourth is the first part of the split.
            if process.decode_count == 4:
                holder["engine"].jobs[-1].cancel()
            return (
                "ok",
                TranscriptionResult(
                    text=f"recognized phrase {process.decode_count}", duration_seconds=1.0
                ),
            )
        return None

    process = FakeAsrProcess(pid=713, reply=reply)
    process.decode_count = 0
    engine = _engine(tmp_path, process, speaker_tracker_factory=LevelTracker)
    holder["engine"] = engine
    engine._segmenter_factory = VoiceChangeSegmenter
    source = tmp_path / "meeting.wav"
    soundfile.write(source, _voice_change_samples(), 16000)
    job = engine.submit(source, diarize=True)
    try:
        _wait_for(job, "cancelled")
        assert process.decode_count == 4
        assert len(job.progress.completed_lines) == 3
        assert not _sessions(tmp_path).exists() or not list(_sessions(tmp_path).iterdir())
    finally:
        engine.close()


def test_a_cancel_stops_the_second_decode_between_its_blocks(tmp_path, monkeypatch):
    real = engine_module.iter_media_audio
    decodes = []
    holder = {}

    def counted(*args, **options):
        decodes.append(0)
        for block in real(*args, **options):
            decodes[-1] += 1
            # The second decode is the one of the speech pass.
            if len(decodes) == 2 and decodes[-1] == 2:
                holder["job"].cancel()
            yield block

    def no_pass(*_args, **_options):
        raise AssertionError("a cancelled read runs no pass")

    monkeypatch.setattr(engine_module, "iter_media_audio", counted)
    monkeypatch.setattr(voice_split, "find_speech_pieces", no_pass)
    engine, job = _voice_change_job(tmp_path, diarize=True)
    holder["job"] = job
    try:
        _wait_for(job, "cancelled")
    finally:
        engine.close()
    assert len(decodes) == 2
    assert decodes[1] == 2 < decodes[0]
    assert not _sessions(tmp_path).exists() or not list(_sessions(tmp_path).iterdir())


def test_a_file_job_without_diarization_does_not_split(tmp_path):
    process = _file_asr_process()
    engine, job = _voice_change_job(tmp_path, process, diarize=False)
    try:
        _wait_for(job, "completed")
        assert len(job.progress.completed_lines) == 3
        assert process.decode_count == 3
    finally:
        engine.close()
