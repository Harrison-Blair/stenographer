# SPDX-License-Identifier: GPL-3.0-or-later
"""File job queue behavior at media and ASR process boundaries."""

from __future__ import annotations

import json
import queue
import threading
import time

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


def _engine(tmp_path, process, **kwargs):
    return FilesEngine(
        Config.defaults(),
        data_dir=tmp_path / "data",
        decoder=SubprocessFfmpegDecoder(),
        transport=FakeAsrTransport(process),
        segmenter_factory=FakeSegmenter,
        **kwargs,
    )


def test_file_job_exports_phrase_text_and_progress_preview(tmp_path):
    process = FakeAsrProcess()
    engine = _engine(tmp_path, process)
    job = engine.submit(
        _audio(tmp_path / "meeting.wav"),
        diarize=False,
        output_format="txt",
        output_folder=tmp_path / "exports",
    )
    try:
        assert job.wait(5) == "completed"
        assert job.output_path == tmp_path / "exports" / "meeting.txt"
        assert job.output_path.read_text(encoding="utf-8") == (
            "[00:00:00] Speaker 1: recognized phrase 1\n[00:00:01] Speaker 1: recognized phrase 2\n"
        )
        assert len(job.progress.completed_lines) == 2
        assert job.progress.stage == "save"
        assert job.progress.percent == 100
        assert process.sent[0][0] == "load"
        assert [message[0] for message in process.sent[1:]] == ["job", "job"]
    finally:
        engine.close()


@pytest.mark.parametrize("output_format", ("md", "jsonl", "srt"))
def test_file_job_exports_each_shared_format(tmp_path, output_format):
    engine = _engine(tmp_path, FakeAsrProcess())
    job = engine.submit(
        _audio(tmp_path / "formats.wav"),
        diarize=False,
        output_format=output_format,
        output_folder=tmp_path / "exports",
    )
    try:
        assert job.wait(5) == "completed"
        content = job.output_path.read_text(encoding="utf-8")
        if output_format == "md":
            assert "**Speaker 1:** recognized phrase 1" in content
        elif output_format == "jsonl":
            rows = [json.loads(row) for row in content.splitlines()]
            assert rows[0]["text"] == "recognized phrase 1"
            assert rows[1]["text"] == "recognized phrase 2"
        else:
            assert "00:00:00,000 --> 00:00:01,000" in content
            assert "Speaker 1: recognized phrase 1" in content
    finally:
        engine.close()


def test_file_job_uses_private_data_files_folder_by_default(tmp_path):
    engine = _engine(tmp_path, FakeAsrProcess())
    job = engine.submit(_audio(tmp_path / "default-folder.wav"), diarize=False)
    try:
        assert job.wait(5) == "completed"
        assert job.output_path == tmp_path / "data" / "files" / "default-folder.md"
        assert job.output_path.stat().st_mode & 0o777 == 0o600
    finally:
        engine.close()


def test_cancel_finishes_current_phrase_without_saving_output(tmp_path):
    started = threading.Event()
    release = threading.Event()
    process = FakeAsrProcess(started=started, release=release)
    engine = _engine(tmp_path, process)
    job = engine.submit(
        _audio(tmp_path / "cancel.wav"),
        diarize=False,
        output_format="jsonl",
        output_folder=tmp_path / "exports",
    )
    progress_events = []
    job.subscribe(progress_events.append)
    try:
        assert started.wait(5)
        assert job.cancel()
        release.set()
        assert job.wait(5) == "cancelled"
        assert process.decode_count == 1
        assert any(event.stage == "transcribe" for event in progress_events)
        assert job.output_path is None
        assert not (tmp_path / "exports").exists()
    finally:
        release.set()
        engine.close()


def test_jobs_run_in_fifo_order(tmp_path):
    started = threading.Event()
    release = threading.Event()
    process = FakeAsrProcess(started=started, release=release)
    engine = _engine(tmp_path, process)
    first = engine.submit(
        _audio(tmp_path / "first.wav"),
        diarize=False,
        output_folder=tmp_path / "exports",
    )
    try:
        assert started.wait(5)
        second = engine.submit(
            _audio(tmp_path / "second.wav"),
            diarize=False,
            output_folder=tmp_path / "exports",
        )
        assert first.state == "running"
        assert second.state == "queued"
        release.set()
        assert first.wait(5) == "completed"
        assert second.wait(5) == "completed"
        assert first.started_at <= second.started_at
        assert "recognized phrase 3" in second.output_path.read_text(encoding="utf-8")
    finally:
        release.set()
        engine.close()


def test_invalid_output_format_is_rejected_before_queueing(tmp_path):
    process = FakeAsrProcess()
    engine = _engine(tmp_path, process)
    try:
        with pytest.raises(ValueError, match="unsupported transcript format"):
            engine.submit(tmp_path / "audio.wav", diarize=False, output_format="html")
        assert not process.sent
        assert engine.jobs == ()
    finally:
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
        assert job.output_path is None
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
        output_format="txt",
        output_folder=tmp_path / "exports",
    )
    try:
        assert job.wait(5) == "completed"
        assert "clean recognized phrase 1" in job.output_path.read_text(encoding="utf-8")
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
        output_format="jsonl",
        output_folder=tmp_path / "exports",
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
