# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-session coordination tests without audio hardware or ASR processes."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.live.phrase import Phrase
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeWriter:
    def __init__(self):
        self.path = Path()
        self.started_at = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
        self.audio = []
        self.silence = []
        self.lines = []
        self.renames = []
        self.closed = False
        self._writer = None

    def open(self, root, _started_at):
        self._writer = SessionWriter.open(root, self.started_at)
        self.path = self._writer.path
        self.started_at = self._writer.started_at

    def write_audio(self, source, samples):
        self.audio.append((source, samples.copy()))
        self._writer.write_audio(source, samples)

    def write_silence(self, source, seconds):
        self.silence.append((source, seconds))
        self._writer.write_silence(source, seconds)

    def append_line(self, line):
        self.lines.append(line)
        self._writer.append_line(line)

    def relabel(self, labels):
        self.renames.append(dict(labels))
        self._writer.relabel(labels)

    def mark_mic_diarized(self):
        self._writer.mark_mic_diarized()

    def close(self):
        self.closed = True
        self._writer.close()


class FakeRecorder:
    def __init__(self, *, on_block, **kwargs):
        self.on_block = on_block
        self.options = kwargs
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def close(self):
        self.running = False

    def emit(self, value):
        self.on_block(np.asarray([value], dtype=np.float32), 16000, 1)


class FakeSystemCapture:
    def __init__(self, available=True, reason=None):
        self.on_block = None
        self.running = False
        self.availability = available, reason

    def available(self):
        return self.availability

    def start(self, on_block):
        self.on_block = on_block
        self.running = True

    def stop(self):
        self.running = False

    def emit(self, value):
        self.on_block(np.asarray([value], dtype=np.float32))


class FakePlatform:
    def __init__(self, system_capture, data_path, platform_error=None):
        self._system_capture = system_capture
        self._data_path = data_path
        self._platform_error = platform_error

    def data_dir(self, _env, _home):
        return self._data_path

    def system_audio_capture(self):
        if self._platform_error is not None:
            raise self._platform_error
        return self._system_capture

    def asr_transport(self):
        return object()


class FakeSegmenter:
    def __init__(self, source, _model_path, **_kwargs):
        self.source = source
        self.flushed = False

    def accept(self, block):
        value = float(block[0])
        return [
            Phrase(
                source=self.source,
                start=0.25,
                end=0.5,
                samples=np.asarray([value], dtype=np.float32),
            )
        ]

    def flush(self):
        self.flushed = True
        return []


class FakeWorker:
    def __init__(self, _cfg, *, transport):
        assert transport is not None
        self.events = []
        self.calls = []
        self.stopped = False

    def hold_model(self):
        self.events.append("hold")

    def warmup(self):
        self.events.append("warmup")

    def release_model(self):
        self.events.append("release")

    def transcribe(self, samples):
        value = int(samples[0])
        self.calls.append(value)
        if value == 5:
            raise RuntimeError("private fake phrase detail")
        results = {
            1: TranscriptionResult(
                "  spoken words  ",
                1.0,
                [SegmentInfo(0.0, 1.0, "spoken words", 0.1)],
            ),
            2: TranscriptionResult(
                "hallucinated music",
                1.0,
                [SegmentInfo(0.0, 1.0, "hallucinated music", 0.6)],
            ),
            3: TranscriptionResult("  \n", 1.0, [SegmentInfo(0.0, 1.0, "", 0.1)]),
            4: TranscriptionResult(
                "a phrase",
                1.0,
                [
                    SegmentInfo(0.0, 0.5, "a", 0.8),
                    SegmentInfo(0.5, 1.0, "phrase", 0.2),
                ],
            ),
        }
        return results[value]

    def shutdown(self):
        self.events.append("shutdown")
        self.stopped = True


class FakeSpeakerTracker:
    def __init__(self, *_args, **_kwargs):
        self.names = {}
        self.speaker_ids = []

    def embed(self, _samples):
        return np.array([1.0, 0.0], dtype=np.float32)

    def assign_embedding(self, _embedding, *, duration=None):
        if "speaker-1" not in self.speaker_ids:
            self.speaker_ids.append("speaker-1")
        return "speaker-1"

    def assign(self, samples):
        return self.assign_embedding(self.embed(samples))

    def label(self, speaker_id):
        return "You" if speaker_id == "you" else self.names.get(speaker_id, "Speaker 1")

    def rename(self, speaker_id, name):
        self.names[speaker_id] = name.strip()


def _make_session(
    monkeypatch,
    tmp_path,
    *,
    clock=None,
    mic=True,
    system=True,
    availability=(True, None),
    platform_error=None,
    start=True,
    feedback_floor=-45.0,
    tracker=None,
    **session_options,
):
    import stenographer.lib.live.live_session as live_session

    writer = FakeWriter()
    system_capture = FakeSystemCapture(*availability)
    worker_holder = {}
    recorder_holder = {}
    segmenters = []

    class WriterFactory:
        @staticmethod
        def open(root, started_at):
            writer.open(root, started_at)
            return writer

    class WorkerFactory(FakeWorker):
        def __init__(self, cfg, *, transport):
            super().__init__(cfg, transport=transport)
            worker_holder["worker"] = self

    class RecorderFactory(FakeRecorder):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            recorder_holder["recorder"] = self

    class SegmenterFactory(FakeSegmenter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            segmenters.append(self)

    monkeypatch.setattr(live_session, "SessionWriter", WriterFactory)
    monkeypatch.setattr(live_session, "Worker", WorkerFactory)
    monkeypatch.setattr(live_session, "Recorder", RecorderFactory)
    monkeypatch.setattr(live_session, "PhraseSegmenter", SegmenterFactory)
    monkeypatch.setattr(live_session, "SpeakerTracker", tracker or FakeSpeakerTracker)
    platform = FakePlatform(system_capture, tmp_path, platform_error)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(model="test-model"),
        audio=SimpleNamespace(input_device=None),
        feedback=SimpleNamespace(spectrum_floor_dbfs=feedback_floor),
    )
    session = live_session.LiveSession(
        cfg,
        mic=mic,
        system=system,
        platform=platform,
        monotonic=clock or FakeClock(),
        **session_options,
    )
    if start:
        session.start()
    return (
        session,
        writer,
        worker_holder["worker"],
        system_capture,
        recorder_holder["recorder"],
        segmenters,
    )


def test_start_warms_the_worker_before_starting_live_sources(monkeypatch, tmp_path):
    session, _writer, worker, system, recorder, _segmenters = _make_session(monkeypatch, tmp_path)

    assert worker.events[:2] == ["hold", "warmup"]
    assert recorder.running
    assert system.running
    session.stop()


def test_live_session_queues_sources_in_order_filters_d12_and_drains_on_stop(
    monkeypatch, tmp_path, caplog
):
    delivered = []
    session, writer, worker, system, recorder, segmenters = _make_session(monkeypatch, tmp_path)
    session.subscribe(delivered.append)

    recorder.emit(1)
    assert session.levels_dbfs["mic"] == 0.0
    assert session.source_states["mic"] == "on"
    assert session.model_name == "test-model"
    assert recorder.options["streaming"] is True
    assert recorder.options["max_seconds"] == 0
    system.emit(2)
    system.emit(3)
    system.emit(4)
    session.stop()

    assert worker.calls == [1, 2, 3, 4]
    assert [line.text for line in writer.lines] == ["spoken words", "a phrase"]
    assert delivered == writer.lines
    assert writer.lines[0].source == "mic"
    assert writer.lines[0].speaker_id == "you"
    assert writer.lines[0].label == "You"
    assert writer.lines[1].source == "system"
    assert writer.lines[1].speaker_id == "speaker-1"
    assert writer.lines[1].label == "Speaker 1"
    assert writer.lines[0].start == 0.25
    assert writer.lines[0].wall == "2026-03-02T04:05:06.250000+00:00"
    assert writer.closed
    assert worker.events == ["hold", "warmup", "release", "shutdown"]
    assert worker.stopped
    assert len(segmenters) == 2
    assert all(segmenter.flushed for segmenter in segmenters)
    assert "spoken words" not in caplog.text
    assert "hallucinated music" not in caplog.text


def test_stop_relabels_the_saved_session_revision_and_preserves_a_rename(monkeypatch, tmp_path):
    session, writer, _worker, system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, mic=False
    )
    processed = Event()
    session.subscribe(lambda _line: processed.set())

    system.emit(4)
    assert processed.wait(timeout=1)
    session.rename("speaker-1", "Alice")
    session.stop()

    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert writer.closed
    assert detail.revision == "transcript.r2.jsonl"
    assert [line.label for line in detail.lines] == ["Alice"]


def test_second_stop_request_skips_relabel_and_keeps_the_live_revision(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    started = Event()
    release = Event()
    original_relabel = live_session.relabel_system_lines

    def wait_for_skip(lines, embeddings, **kwargs):
        started.set()
        release.wait(timeout=1)
        if kwargs["should_cancel"]():
            return None
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(live_session, "relabel_system_lines", wait_for_skip)
    session, writer, _worker, system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, mic=False
    )
    processed = Event()
    session.subscribe(lambda _line: processed.set())
    system.emit(4)
    assert processed.wait(timeout=1)
    failures = []

    def stop_session():
        try:
            session.stop()
        except Exception as exc:
            failures.append(exc)

    stop_thread = Thread(target=stop_session)
    stop_thread.start()
    assert started.wait(timeout=1)
    assert session.relabel_status == "Relabeling speakers 0/1 · q to skip"
    session.skip_relabel()
    release.set()
    stop_thread.join(timeout=1)
    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert not stop_thread.is_alive()
    assert failures == []
    assert session.relabel_status == "Relabeling skipped"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Speaker 1"]


def test_relabel_failure_keeps_live_labels_and_exposes_the_reason(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    def fail_relabel(*_args, **_kwargs):
        raise RuntimeError("batch clustering unavailable")

    monkeypatch.setattr(live_session, "relabel_system_lines", fail_relabel)
    session, writer, _worker, system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, mic=False
    )
    processed = Event()
    session.subscribe(lambda _line: processed.set())

    system.emit(4)
    assert processed.wait(timeout=1)
    session.stop()
    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert session.relabel_error == "batch clustering unavailable"
    assert session.relabel_status == "Relabeling failed: batch clustering unavailable"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Speaker 1"]


def test_pause_freezes_clock_and_silence_writes_and_rename_updates_old_lines(monkeypatch, tmp_path):
    clock = FakeClock()
    session, writer, _worker, system, _recorder, segmenters = _make_session(
        monkeypatch, tmp_path, clock=clock
    )
    processed = Event()
    session.subscribe(lambda _line: processed.set())
    system.emit(4)
    assert processed.wait(timeout=1)
    assert session.lines[0].speaker_id == "speaker-1"

    session.rename("speaker-1", "Alice")
    assert session.lines[0].label == "Alice"
    assert writer.renames == [{"speaker-1": "Alice"}]
    processed.clear()
    system.emit(4)
    assert processed.wait(timeout=1)
    assert session.lines[-1].label == "Alice"
    assert writer.lines[-1].label == "Alice"

    clock.now = 2.0
    session.pause()
    elapsed = session.elapsed_seconds
    writes = list(writer.silence)
    clock.now = 20.0
    assert session.elapsed_seconds == elapsed
    assert writer.silence == writes

    session.resume()
    clock.now = 21.0
    session.stop()
    assert all(segmenter.flushed for segmenter in segmenters)
    assert session.elapsed_seconds == 3.0
    assert writer.closed
    assert not system.running


def test_stop_before_start_closes_resources_without_waiting_for_a_consumer(monkeypatch, tmp_path):
    session, writer, worker, _system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, start=False
    )

    session.stop()

    assert writer.closed
    assert worker.stopped


def test_unsupported_system_platform_disables_system_without_blocking_mic(monkeypatch, tmp_path):
    from stenographer.lib.platform.errors import UnsupportedPlatformError

    reason = "system audio capture is unavailable"
    session, writer, worker, _system, _recorder, _segmenters = _make_session(
        monkeypatch,
        tmp_path,
        platform_error=UnsupportedPlatformError(reason),
    )

    assert session.source_states["mic"] == "on"
    assert session.source_states["system"] == "off"
    assert session.source_reasons["system"] == reason

    session.toggle("system")
    assert session.source_states["system"] == "off"
    assert session.source_reasons["system"] == reason
    session.stop()
    assert writer.closed
    assert worker.stopped


@pytest.mark.skipif(sys.platform != "linux", reason="Linux PipeWire capture routing")
def test_live_session_disables_misrouted_pipewire_system_capture(monkeypatch, tmp_path):
    from stenographer.lib.platform.linux.system_audio import LinuxSystemAudioCapture

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pactl = bin_dir / "pactl"
    pactl.write_text("#!/bin/sh\nprintf 'studio\\n'\n")
    pactl.chmod(0o755)
    pw_record = bin_dir / "pw-record"
    pw_record.write_text(
        f"#!{sys.executable}\n"
        "import os, struct, sys, time\n"
        "from pathlib import Path\n"
        "Path(os.environ['PW_LIVE_PID']).write_text(str(os.getpid()))\n"
        "sys.stdout.buffer.write(struct.pack('<512f', *([1.0] * 512)))\n"
        "sys.stdout.buffer.flush()\n"
        "while True: time.sleep(0.05)\n"
    )
    pw_record.chmod(0o755)
    pw_link = bin_dir / "pw-link"
    pw_link.write_text(
        f"#!{sys.executable}\n"
        "print('microphone:capture_FL')\n"
        "print('  |-> stenographer-system-capture:input_FL')\n"
        "print('microphone:capture_FR')\n"
        "print('  |-> stenographer-system-capture:input_FR')\n"
    )
    pw_link.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PW_LIVE_PID", str(tmp_path / "pid.txt"))

    session, writer, _worker, _fake_system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, mic=False, start=False
    )
    session._system_capture = LinuxSystemAudioCapture()
    try:
        session.start()

        assert session.source_states["system"] == "off"
        assert (
            session.source_reasons["system"] == "system capture is not linked to the sink monitor"
        )
        assert not any(source == "system" for source, _samples in writer.audio)
    finally:
        session.stop()

    process_id = int((tmp_path / "pid.txt").read_text())
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("pw-record stayed alive after the link check failed")


def test_unavailable_system_source_stays_off_and_exposes_the_reason(monkeypatch, tmp_path):
    reason = "pw-record is not installed"
    session, writer, worker, system, _recorder, _segmenters = _make_session(
        monkeypatch,
        tmp_path,
        mic=False,
        availability=(False, reason),
    )

    assert session.source_states["system"] == "off"
    assert session.source_reasons["system"] == reason
    assert not system.running

    session.toggle("system")
    assert session.source_states["system"] == "off"
    assert session.source_reasons["system"] == reason
    assert not system.running

    session.stop()
    assert writer.closed
    assert worker.stopped


def test_toggle_off_catches_up_with_silence_and_stop_shuts_sources(monkeypatch, tmp_path):
    clock = FakeClock()
    session, writer, worker, system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, clock=clock
    )
    clock.now = 1.0
    session.toggle("mic")
    assert session.source_states["mic"] == "off"
    assert writer.silence == [("mic", 1.0)]

    clock.now = 2.0
    session.toggle("mic")
    assert session.source_states["mic"] == "on"
    assert writer.silence[-1] == ("mic", 1.0)

    session.stop()
    assert not recorder.running
    assert not system.running
    assert worker.stopped
    assert writer.closed


def test_meter_floor_uses_the_low_frequency_profile_value(monkeypatch, tmp_path):
    session, writer, _worker, _system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, start=False, feedback_floor=(-81.0, -65.0, -72.0)
    )

    assert session.meter_floor_dbfs == -81.0
    session.stop()
    assert writer.closed


def test_missing_meter_floor_uses_minus_seventy_dbfs(monkeypatch, tmp_path):
    session, _writer, _worker, _system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, start=False, feedback_floor=None
    )

    assert session.meter_floor_dbfs == -70.0
    session.stop()


def test_failed_phrase_increments_the_failure_count(monkeypatch, tmp_path, caplog):
    session, _writer, _worker, system, _recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, mic=False
    )

    system.emit(5)
    session._queue.join()

    assert session.failed_phrase_count == 1
    assert session.lines == ()
    assert "private fake phrase detail" not in caplog.text
    session.stop()


def test_transcript_line_values_use_the_source_session_clock():
    line = TranscriptLine(1.0, 2.0, "wall", "system", "speaker-1", "Speaker 1", "words")

    assert line.start == 1.0
    assert line.source == "system"
    assert line.text == "words"


class VoiceSpeakerTracker:
    """Give each fake phrase value its own voice and number voices per prefix."""

    def __init__(self, *_args, label_prefix="Speaker", **_kwargs):
        self.prefix = label_prefix
        self.voices = {}
        self.names = {}

    @property
    def speaker_ids(self):
        return tuple(self.voices.values())

    def embed(self, samples):
        return np.array([1.0, 0.0] if samples[0] == 1 else [0.0, 1.0], dtype=np.float32)

    def assign_embedding(self, embedding, *, duration=None):
        key = tuple(float(value) for value in embedding)
        if key not in self.voices:
            self.voices[key] = f"{self.prefix.lower()}-{len(self.voices) + 1}"
        return self.voices[key]

    def label(self, speaker_id):
        if speaker_id == "you":
            return "You"
        number = speaker_id.removeprefix(f"{self.prefix.lower()}-")
        return self.names.get(speaker_id, f"{self.prefix} {number}")

    def rename(self, speaker_id, name):
        if speaker_id not in self.voices.values():
            raise ValueError(f"Unknown speaker ID: {speaker_id}")
        self.names[speaker_id] = name.strip()


def _wait_for_lines(session, count):
    processed = Event()

    def seen(_line):
        if len(session.lines) >= count:
            processed.set()

    session.subscribe(seen)
    return processed


def test_mic_phrases_stay_you_when_mic_diarization_is_off(monkeypatch, tmp_path):
    session, writer, _worker, _system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, system=False, tracker=VoiceSpeakerTracker
    )
    processed = _wait_for_lines(session, 2)

    recorder.emit(1)
    recorder.emit(4)
    assert processed.wait(timeout=1)
    session.stop()

    assert [(line.speaker_id, line.label) for line in writer.lines] == [
        ("you", "You"),
        ("you", "You"),
    ]
    assert session.speakers == ()
    assert not (writer.path / "session.json").exists()
    assert SessionStore(writer.path.parent).read(writer.path.name).diarize_mic is False


def test_mic_diarization_labels_room_speakers_apart_from_system_speakers(monkeypatch, tmp_path):
    session, writer, _worker, system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, tracker=VoiceSpeakerTracker, diarize_mic=True
    )
    processed = _wait_for_lines(session, 3)

    recorder.emit(1)
    recorder.emit(4)
    system.emit(1)
    assert processed.wait(timeout=1)

    assert [(line.source, line.speaker_id, line.label) for line in writer.lines] == [
        ("mic", "room-1", "Room 1"),
        ("mic", "room-2", "Room 2"),
        ("system", "speaker-1", "Speaker 1"),
    ]
    assert set(session.speakers) == {
        ("room-1", "Room 1"),
        ("room-2", "Room 2"),
        ("speaker-1", "Speaker 1"),
    }
    session.stop()
    assert SessionStore(writer.path.parent).read(writer.path.name).diarize_mic is True


def test_stop_relabels_mic_lines_separately_with_the_room_prefix(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines
    passes = []

    def record_pass(lines, embeddings, **kwargs):
        lines = tuple(lines)
        passes.append(({line.source for line in lines}, kwargs.get("label_prefix", "Speaker")))
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(live_session, "relabel_system_lines", record_pass)
    session, writer, _worker, system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, tracker=VoiceSpeakerTracker, diarize_mic=True
    )
    processed = _wait_for_lines(session, 3)
    recorder.emit(1)
    recorder.emit(4)
    system.emit(4)
    assert processed.wait(timeout=1)
    session.stop()

    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert sorted(passes, key=lambda item: item[1]) == [({"mic"}, "Room"), ({"system"}, "Speaker")]
    assert detail.revision == "transcript.r2.jsonl"
    # Every fake phrase is shorter than an anchor, so each pass keeps one voice.
    assert [(line.source, line.speaker_id, line.label) for line in detail.lines] == [
        ("mic", "room-1", "Room 1"),
        ("mic", "room-1", "Room 1"),
        ("system", "speaker-1", "Speaker 1"),
    ]
    assert detail.diarize_mic is True


def test_rename_updates_a_room_speaker_and_its_existing_lines(monkeypatch, tmp_path):
    session, writer, _worker, _system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, system=False, tracker=VoiceSpeakerTracker, diarize_mic=True
    )
    processed = _wait_for_lines(session, 2)
    recorder.emit(1)
    recorder.emit(4)
    assert processed.wait(timeout=1)

    session.rename("room-2", "Dana")

    assert [line.label for line in session.lines] == ["Room 1", "Dana"]
    assert writer.renames == [{"room-2": "Dana"}]
    assert ("room-2", "Dana") in session.speakers
    session.stop()


def test_skip_during_mic_relabel_keeps_live_room_labels(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    started = Event()
    release = Event()

    def wait_for_skip(lines, embeddings, **kwargs):
        started.set()
        release.wait(timeout=1)
        return None if kwargs["should_cancel"]() else tuple(lines)

    monkeypatch.setattr(live_session, "relabel_system_lines", wait_for_skip)
    session, writer, _worker, system, recorder, _segmenters = _make_session(
        monkeypatch, tmp_path, tracker=VoiceSpeakerTracker, diarize_mic=True
    )
    processed = _wait_for_lines(session, 3)
    recorder.emit(1)
    recorder.emit(4)
    system.emit(1)
    assert processed.wait(timeout=1)
    stop_thread = Thread(target=session.stop)
    stop_thread.start()
    assert started.wait(timeout=1)
    assert session.relabel_status == "Relabeling speakers 0/3 · q to skip"
    session.skip_relabel()
    release.set()
    stop_thread.join(timeout=1)
    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert not stop_thread.is_alive()
    assert session.relabel_status == "Relabeling skipped"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Room 1", "Room 2", "Speaker 1"]
