# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-session coordination tests without audio hardware or ASR processes."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from stenographer.lib.live import voice_split
from stenographer.lib.live.phrase_segmenter import Phrase
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.speaker_tracker import SpeakerTracker
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult
from tests.lib.live.speech_support import level_pieces
from tests.lib.platform.support import NullProcessCounters
from tests.support import wait_until


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

    def process_counters(self):
        return NullProcessCounters()


class FakeSegmenter:
    def __init__(self, source, _model_path, **_kwargs):
        self.source = source
        self.flushed = False
        self.speech_detected = False

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
                [SegmentInfo(0.0, 1.0, "spoken words")],
            ),
            # Bark has no no-speech estimate: a phrase with text is always kept.
            2: TranscriptionResult(
                "quiet music words",
                1.0,
                [SegmentInfo(0.0, 1.0, "quiet music words")],
            ),
            3: TranscriptionResult("  \n", 1.0, [SegmentInfo(0.0, 1.0, "")]),
            4: TranscriptionResult(
                "a phrase",
                1.0,
                [
                    SegmentInfo(0.0, 0.5, "a"),
                    SegmentInfo(0.5, 1.0, "phrase"),
                ],
            ),
        }
        return results[value]

    def shutdown(self):
        self.events.append("shutdown")
        self.stopped = True


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
    monkeypatch.setattr(live_session, "SpeakerTracker", tracker or VoiceSpeakerTracker)
    saved_audio = {}

    def read_saved_source(path):
        said = {key: value for key, value in saved_audio.items() if key[0] == path.stem}
        whole = np.zeros(1 + max((round(key[2] * 16000) for key in said), default=0), np.float32)
        for (_source, start, _end), samples in said.items():
            first = round(start * 16000)
            whole[first : first + samples.size] = samples
        return whole

    monkeypatch.setattr(live_session, "read_saved_source", read_saved_source)
    # Most tests are about the groups of whole lines, so the pass finds no speech.
    monkeypatch.setattr(voice_split, "find_speech_pieces", lambda *_args, **_options: ())
    platform = FakePlatform(system_capture, tmp_path, platform_error)
    cfg = SimpleNamespace(
        asr=SimpleNamespace(),
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
    return SimpleNamespace(
        session=session,
        writer=writer,
        worker=worker_holder["worker"],
        system=system_capture,
        recorder=recorder_holder["recorder"],
        segmenters=segmenters,
        saved_audio=saved_audio,
    )


def test_start_warms_the_worker_before_starting_live_sources(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)

    assert rig.worker.events[:2] == ["hold", "warmup"]
    assert rig.recorder.running
    assert rig.system.running
    rig.session.stop()


def test_live_session_queues_sources_in_order_filters_d12_and_drains_on_stop(
    monkeypatch, tmp_path, caplog
):
    delivered = []
    rig = _make_session(monkeypatch, tmp_path)
    rig.session.subscribe(delivered.append)

    rig.recorder.emit(1)
    assert rig.session.levels_dbfs["mic"] == 0.0
    assert rig.session.source_states["mic"] == "on"
    assert rig.session.model_name == "bark-pro-int8"
    assert rig.recorder.options["streaming"] is True
    assert rig.recorder.options["max_seconds"] == 0
    rig.system.emit(2)
    rig.system.emit(3)
    rig.system.emit(4)
    rig.session.stop()

    assert rig.worker.calls == [1, 2, 3, 4]
    assert [line.text for line in rig.writer.lines] == [
        "spoken words",
        "quiet music words",
        "a phrase",
    ]
    assert delivered == rig.writer.lines
    assert rig.writer.lines[0].source == "mic"
    assert rig.writer.lines[0].speaker_id == "you"
    assert rig.writer.lines[0].label == "You"
    assert rig.writer.lines[1].source == "system"
    assert rig.writer.lines[1].speaker_id == "speaker-1"
    assert rig.writer.lines[1].label == "Speaker 1"
    assert rig.writer.lines[0].start == 0.25
    assert rig.writer.lines[0].wall == "2026-03-02T04:05:06.250000+00:00"
    assert rig.writer.closed
    assert rig.worker.events == ["hold", "warmup", "release", "shutdown"]
    assert rig.worker.stopped
    assert len(rig.segmenters) == 2
    assert all(segmenter.flushed for segmenter in rig.segmenters)
    assert "spoken words" not in caplog.text
    assert "quiet music words" not in caplog.text


def test_stop_relabels_the_saved_session_revision_and_preserves_a_rename(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    processed = Event()
    rig.session.subscribe(lambda _line: processed.set())

    rig.system.emit(4)
    assert processed.wait(timeout=1)
    rig.session.rename("speaker-1", "Alice")
    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)

    assert rig.writer.closed
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

    monkeypatch.setattr(voice_split, "relabel_system_lines", wait_for_skip)
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    processed = Event()
    rig.session.subscribe(lambda _line: processed.set())
    rig.system.emit(4)
    assert processed.wait(timeout=1)
    failures = []

    def stop_session():
        try:
            rig.session.stop()
        except Exception as exc:
            failures.append(exc)

    stop_thread = Thread(target=stop_session)
    stop_thread.start()
    assert started.wait(timeout=1)
    assert rig.session.relabel_status == "Relabeling speakers 0/1 · q to skip"
    rig.session.skip_relabel()
    release.set()
    stop_thread.join(timeout=1)
    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)

    assert not stop_thread.is_alive()
    assert failures == []
    assert rig.session.relabel_status == "Relabeling skipped"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Speaker 1"]


def test_relabel_failure_keeps_live_labels_and_exposes_the_reason(monkeypatch, tmp_path):

    def fail_relabel(*_args, **_kwargs):
        raise RuntimeError("batch clustering unavailable")

    monkeypatch.setattr(voice_split, "relabel_system_lines", fail_relabel)
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    processed = Event()
    rig.session.subscribe(lambda _line: processed.set())

    rig.system.emit(4)
    assert processed.wait(timeout=1)
    rig.session.stop()
    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)

    assert rig.session.relabel_error == "batch clustering unavailable"
    assert rig.session.relabel_status == "Relabeling failed: batch clustering unavailable"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Speaker 1"]


def test_relabel_stale_revision_keeps_a_rename_saved_during_the_pass(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines
    holder = {}

    def rename_during_pass(lines, embeddings, **kwargs):
        writer = holder["writer"]
        SessionStore(writer.path.parent).rename_speaker(writer.path.name, "speaker-1", "Alice")
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(voice_split, "relabel_system_lines", rename_during_pass)
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    writer = rig.writer
    holder["writer"] = writer
    processed = Event()
    rig.session.subscribe(lambda _line: processed.set())

    rig.system.emit(4)
    assert processed.wait(timeout=1)
    rig.session.stop()
    detail = SessionStore(writer.path.parent).read(writer.path.name)

    assert detail.revision == "transcript.r2.jsonl"
    assert [(line.speaker_id, line.label, line.text) for line in detail.lines] == [
        ("speaker-1", "Alice", "a phrase")
    ]
    assert "changed since it was read" in rig.session.relabel_error
    assert [(line.speaker_id, line.label) for line in rig.session.lines] == [
        ("speaker-1", "Speaker 1")
    ]


def test_pause_freezes_clock_and_silence_writes_and_rename_updates_old_lines(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    processed = Event()
    rig.session.subscribe(lambda _line: processed.set())
    rig.system.emit(4)
    assert processed.wait(timeout=1)
    assert rig.session.lines[0].speaker_id == "speaker-1"

    rig.session.rename("speaker-1", "Alice")
    assert rig.session.lines[0].label == "Alice"
    assert rig.writer.renames == [{"speaker-1": "Alice"}]
    processed.clear()
    rig.system.emit(4)
    assert processed.wait(timeout=1)
    assert rig.session.lines[-1].label == "Alice"
    assert rig.writer.lines[-1].label == "Alice"

    clock.now = 2.0
    rig.session.pause()
    elapsed = rig.session.elapsed_seconds
    writes = list(rig.writer.silence)
    clock.now = 20.0
    assert rig.session.elapsed_seconds == elapsed
    assert rig.writer.silence == writes

    rig.session.resume()
    clock.now = 21.0
    rig.session.stop()
    assert all(segmenter.flushed for segmenter in rig.segmenters)
    assert rig.session.elapsed_seconds == 3.0
    assert rig.writer.closed
    assert not rig.system.running


def test_stop_before_start_closes_resources_without_waiting_for_a_consumer(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, start=False)

    rig.session.stop()

    assert rig.writer.closed
    assert rig.worker.stopped


def test_unsupported_system_platform_disables_system_without_blocking_mic(
    monkeypatch, tmp_path, caplog
):
    from stenographer.lib.platform.errors import UnsupportedPlatformError

    reason = "system audio capture is unavailable"
    rig = _make_session(
        monkeypatch,
        tmp_path,
        platform_error=UnsupportedPlatformError(reason),
    )

    assert rig.session.source_states["mic"] == "on"
    assert rig.session.source_states["system"] == "off"
    assert f'live: system_source_unavailable error=UnsupportedPlatformError detail="{reason}"' in (
        caplog.text
    )

    rig.session.toggle("system")
    assert rig.session.source_states["system"] == "off"
    rig.session.stop()
    assert rig.writer.closed
    assert rig.worker.stopped


@pytest.mark.skipif(sys.platform != "linux", reason="Linux PipeWire capture routing")
def test_live_session_disables_misrouted_pipewire_system_capture(monkeypatch, tmp_path, caplog):
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

    rig = _make_session(monkeypatch, tmp_path, mic=False, start=False)
    rig.session._system_capture = LinuxSystemAudioCapture()
    try:
        rig.session.start()

        assert rig.session.source_states["system"] == "off"
        assert "system capture is not linked to the sink monitor" in caplog.text
        assert not any(source == "system" for source, _samples in rig.writer.audio)
    finally:
        rig.session.stop()

    process_id = int((tmp_path / "pid.txt").read_text())
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("pw-record stayed alive after the link check failed")


def test_unavailable_system_source_stays_off_and_logs_the_reason(monkeypatch, tmp_path, caplog):
    reason = "pw-record is not installed"
    rig = _make_session(
        monkeypatch,
        tmp_path,
        mic=False,
        availability=(False, reason),
    )

    logged = f'live: system_source_unavailable reason="{reason}"'
    assert rig.session.source_states["system"] == "off"
    assert caplog.text.count(logged) == 1
    assert not rig.system.running

    rig.session.toggle("system")
    assert rig.session.source_states["system"] == "off"
    assert caplog.text.count(logged) == 2
    assert not rig.system.running

    rig.session.stop()
    assert rig.writer.closed
    assert rig.worker.stopped


def test_toggle_off_catches_up_with_silence_and_stop_shuts_sources(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    clock.now = 1.0
    rig.session.toggle("mic")
    assert rig.session.source_states["mic"] == "off"
    assert rig.writer.silence == [("mic", 1.0)]

    clock.now = 2.0
    rig.session.toggle("mic")
    assert rig.session.source_states["mic"] == "on"
    assert rig.writer.silence[-1] == ("mic", 1.0)

    rig.session.stop()
    assert not rig.recorder.running
    assert not rig.system.running
    assert rig.worker.stopped
    assert rig.writer.closed


def test_meter_floor_uses_the_low_frequency_profile_value(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, start=False, feedback_floor=(-81.0, -65.0, -72.0))

    assert rig.session.meter_floor_dbfs == -81.0
    rig.session.stop()
    assert rig.writer.closed


def test_failed_phrase_increments_the_failure_count(monkeypatch, tmp_path, caplog):
    rig = _make_session(monkeypatch, tmp_path, mic=False)

    rig.system.emit(5)
    rig.session._queue.join()

    assert rig.session.failed_phrase_count == 1
    assert rig.session.lines == ()
    assert "private fake phrase detail" not in caplog.text
    rig.session.stop()


def test_audio_write_failure_keeps_transcribing_and_reports_the_source(
    monkeypatch, tmp_path, caplog
):
    rig = _make_session(monkeypatch, tmp_path, system=False)
    # The real writer refuses to replace an existing audio file.
    (rig.session.path / "mic.flac").touch()

    rig.recorder.emit(1)
    rig.recorder.emit(1)
    rig.session._queue.join()

    assert [line.text for line in rig.session.lines] == ["spoken words", "spoken words"]
    assert rig.session.audio_failed_sources == ("mic",)
    assert len(rig.writer.audio) == 1
    assert caplog.text.count("live: audio_save_failed") == 1
    rig.session.stop()
    assert rig.session.audio_failed_sources == ("mic",)
    assert (rig.session.path / "transcript.md").exists()


def test_stop_finishes_when_padding_fails(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    rig.system.emit(1)
    clock.now = 1.0
    (rig.session.path / "mic.flac").touch()

    rig.session.stop()

    assert rig.session.audio_failed_sources == ("mic",)
    assert not rig.recorder.running
    assert not rig.system.running
    assert [line.text for line in rig.session.lines] == ["spoken words"]
    assert rig.writer.closed
    assert rig.worker.stopped
    assert (rig.session.path / "transcript.md").exists()
    assert rig.session.relabel_status == ""


class VoiceSpeakerTracker(SpeakerTracker):
    """Run the real speaker logic and give each fake phrase value its own voice."""

    def __init__(self, *_args, label_prefix="Speaker", **_kwargs):
        model = SimpleNamespace(
            SpeakerEmbeddingExtractorConfig=lambda **_options: None,
            SpeakerEmbeddingExtractor=lambda _config: None,
        )
        with patch.dict(sys.modules, {"sherpa_onnx": model}):
            super().__init__("speaker.onnx", label_prefix=label_prefix)

    def embed(self, samples):
        voices = {1: (1.0, 0.0, 0.0), 4: (0.0, 1.0, 0.0), 2: (0.0, 0.0, 1.0)}
        return np.array(voices[int(samples[0])], dtype=np.float32)


def _wait_for_lines(session, count):
    processed = Event()

    def seen(_line):
        if len(session.lines) >= count:
            processed.set()

    session.subscribe(seen)
    return processed


def test_mic_phrases_stay_you_when_mic_diarization_is_off(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, system=False)
    processed = _wait_for_lines(rig.session, 2)

    rig.recorder.emit(1)
    rig.recorder.emit(4)
    assert processed.wait(timeout=1)
    rig.session.stop()

    assert [(line.speaker_id, line.label) for line in rig.writer.lines] == [
        ("you", "You"),
        ("you", "You"),
    ]
    assert rig.session.speakers == ()
    assert "diarize_mic" not in json.loads((rig.writer.path / "session.json").read_text())
    assert SessionStore(rig.writer.path.parent).read(rig.writer.path.name).diarize_mic is False


def test_mic_diarization_labels_room_speakers_apart_from_system_speakers(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 3)

    rig.recorder.emit(1)
    rig.recorder.emit(4)
    rig.system.emit(1)
    assert processed.wait(timeout=1)

    assert [(line.source, line.speaker_id, line.label) for line in rig.writer.lines] == [
        ("mic", "room-1", "Room 1"),
        ("mic", "room-1", "Room 1"),
        ("system", "speaker-1", "Speaker 1"),
    ]
    assert set(rig.session.speakers) == {
        ("room-1", "Room 1"),
        ("speaker-1", "Speaker 1"),
    }
    rig.session.stop()
    assert SessionStore(rig.writer.path.parent).read(rig.writer.path.name).diarize_mic is True


def test_stop_relabels_mic_lines_separately_with_the_room_prefix(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines
    passes = []

    def record_pass(lines, embeddings, **kwargs):
        lines = tuple(lines)
        passes.append(({line.source for line in lines}, kwargs.get("label_prefix", "Speaker")))
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(voice_split, "relabel_system_lines", record_pass)
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 3)
    rig.recorder.emit(1)
    rig.recorder.emit(4)
    rig.system.emit(4)
    assert processed.wait(timeout=1)
    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)

    assert sorted(passes, key=lambda item: item[1]) == [({"mic"}, "Room"), ({"system"}, "Speaker")]
    assert detail.revision == "transcript.r2.jsonl"
    # Every fake phrase is shorter than an anchor, so each pass keeps one voice.
    assert [(line.source, line.speaker_id, line.label) for line in detail.lines] == [
        ("mic", "room-1", "Room 1"),
        ("mic", "room-1", "Room 1"),
        ("system", "speaker-1", "Speaker 1"),
    ]
    assert detail.diarize_mic is True


def test_stop_relabel_progress_counts_once_across_system_and_mic(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 3)
    rig.recorder.emit(1)
    rig.recorder.emit(4)
    rig.system.emit(1)
    assert processed.wait(timeout=1)
    statuses = []
    record_status = rig.session._set_relabel_progress

    def observe(done, total):
        record_status(done, total)
        statuses.append(rig.session.relabel_status)

    rig.session._set_relabel_progress = observe
    rig.session.stop()

    counts = [tuple(int(part) for part in status.split()[2].split("/")) for status in statuses]
    assert counts
    assert {total for _done, total in counts} == {3}
    assert [done for done, _total in counts] == sorted(done for done, _total in counts)
    assert counts[-1] == (3, 3)


def test_rename_updates_a_room_speaker_and_its_existing_lines(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, system=False, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 2)
    rig.recorder.emit(1)
    rig.recorder.emit(4)
    assert processed.wait(timeout=1)

    rig.session.rename("room-1", "Dana")

    assert [line.label for line in rig.session.lines] == ["Dana", "Dana"]
    assert rig.writer.renames == [{"room-1": "Dana"}]
    assert ("room-1", "Dana") in rig.session.speakers
    rig.session.stop()


def test_skip_during_mic_relabel_keeps_live_room_labels(monkeypatch, tmp_path):

    started = Event()
    release = Event()

    def wait_for_skip(lines, embeddings, **kwargs):
        started.set()
        release.wait(timeout=1)
        return None if kwargs["should_cancel"]() else tuple(lines)

    monkeypatch.setattr(voice_split, "relabel_system_lines", wait_for_skip)
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 3)
    rig.recorder.emit(1)
    rig.recorder.emit(4)
    rig.system.emit(1)
    assert processed.wait(timeout=1)
    stop_thread = Thread(target=rig.session.stop)
    stop_thread.start()
    assert started.wait(timeout=1)
    assert rig.session.relabel_status == "Relabeling speakers 0/3 · q to skip"
    rig.session.skip_relabel()
    release.set()
    stop_thread.join(timeout=1)
    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)

    assert not stop_thread.is_alive()
    assert rig.session.relabel_status == "Relabeling skipped"
    assert detail.revision == "transcript.jsonl"
    assert [line.label for line in detail.lines] == ["Room 1", "Room 1", "Speaker 1"]


class LongPhraseSegmenter(FakeSegmenter):
    """Give each fake phrase anchor length so the real relabel pass clusters it."""

    def accept(self, block):
        return [
            Phrase(
                source=self.source,
                start=0.0,
                end=2.0,
                samples=np.asarray([float(block[0])], dtype=np.float32),
            )
        ]


def test_relabel_progress_counts_phrases_from_the_real_work_units_of_both_passes(
    monkeypatch, tmp_path
):
    import stenographer.lib.live.live_session as live_session

    observed = []
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True, start=False)
    set_progress = rig.session._set_relabel_progress

    def observe_progress(done, total):
        set_progress(done, total)
        observed.append(rig.session.relabel_progress)

    rig.session._set_relabel_progress = observe_progress
    monkeypatch.setattr(live_session, "PhraseSegmenter", LongPhraseSegmenter)
    rig.session.start()
    processed = _wait_for_lines(rig.session, 7)
    for value in (1, 4, 1, 4):
        rig.recorder.emit(value)
    for value in (1, 4, 4):
        rig.system.emit(value)
    assert processed.wait(timeout=1)
    assert rig.session.relabel_progress is None

    rig.session.stop()

    assert observed
    assert {total for _done, total in observed} == {7}
    done = [value for value, _total in observed]
    assert done == sorted(done)
    assert all(0 <= value <= 7 for value in done)
    assert observed[-1] == (7, 7)
    assert rig.session.relabel_progress is None


def test_live_session_exposes_its_worker_pids_and_idle_unload_deadline(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, start=False)
    rig.worker.process_ids = (4321,)
    rig.worker.idle_unload_deadline = 12.5

    assert rig.session.process_ids == (4321,)
    assert rig.session.idle_unload_deadline == 12.5


def test_a_mic_block_is_accepted_while_a_speaker_embedding_runs(monkeypatch, tmp_path):
    accepted_during_embed = []

    class BlockingProbeTracker(VoiceSpeakerTracker):
        def embed(self, samples):
            if not accepted_during_embed:
                block = Thread(target=rig.recorder.emit, args=(4,), daemon=True)
                block.start()
                block.join(timeout=0.5)
                accepted_during_embed.append(not block.is_alive())
            return super().embed(samples)

    rig = _make_session(
        monkeypatch, tmp_path, tracker=BlockingProbeTracker, diarize_mic=True, system=False
    )
    processed = _wait_for_lines(rig.session, 2)

    rig.recorder.emit(1)

    assert processed.wait(timeout=2)
    assert accepted_during_embed == [True]
    rig.session.stop()


def _counting_tracker(created, *, fail=False):
    class CountingTracker(VoiceSpeakerTracker):
        def __init__(self, *args, label_prefix="Speaker", **kwargs):
            if fail:
                raise RuntimeError("fake model failure")
            created.append(label_prefix)
            super().__init__(*args, label_prefix=label_prefix, **kwargs)

    return CountingTracker


def test_a_mic_only_session_loads_no_speaker_model(monkeypatch, tmp_path):
    created = []

    rig = _make_session(monkeypatch, tmp_path, system=False, tracker=_counting_tracker(created))

    assert created == []
    rig.session.stop()
    assert created == []


def test_a_session_with_system_audio_loads_its_speaker_model_at_construction(monkeypatch, tmp_path):
    created = []

    rig = _make_session(monkeypatch, tmp_path, start=False, tracker=_counting_tracker(created))

    assert created == ["Speaker"]
    rig.session.start()
    rig.session.stop()
    assert created == ["Speaker"]


def test_system_toggled_on_later_gets_labels_and_a_relabel_pass(monkeypatch, tmp_path):
    created = []
    rig = _make_session(monkeypatch, tmp_path, system=False, tracker=_counting_tracker(created))
    processed = _wait_for_lines(rig.session, 2)

    rig.recorder.emit(1)
    rig.session.toggle("system")
    rig.system.emit(1)
    assert processed.wait(timeout=1)

    assert created == ["Speaker"]
    assert rig.session.source_states["system"] == "on"
    assert rig.session.speakers == (("speaker-1", "Speaker 1"),)
    rig.session.rename("speaker-1", "Alice")
    rig.session.toggle("system")
    rig.session.toggle("system")
    assert created == ["Speaker"]

    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert detail.revision == "transcript.r2.jsonl"
    assert {(line.source, line.speaker_id) for line in detail.lines} == {
        ("mic", "you"),
        ("system", "speaker-1"),
    }


def test_system_toggled_on_later_keeps_system_speakers_listed_first(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, system=False, diarize_mic=True)
    processed = _wait_for_lines(rig.session, 2)

    rig.recorder.emit(1)
    rig.session.toggle("system")
    rig.system.emit(1)
    assert processed.wait(timeout=1)

    assert rig.session.speakers == (("speaker-1", "Speaker 1"), ("room-1", "Room 1"))
    rig.session.stop()


def test_a_speaker_model_that_fails_on_toggle_leaves_system_off_and_mic_running(
    monkeypatch, tmp_path
):
    rig = _make_session(
        monkeypatch, tmp_path, system=False, tracker=_counting_tracker([], fail=True)
    )
    processed = _wait_for_lines(rig.session, 1)

    rig.session.toggle("system")

    assert rig.session.source_states["system"] == "off"
    rig.recorder.emit(1)
    assert processed.wait(timeout=1)
    rig.session.stop()


VOICE_A, VOICE_B, VOICE_C = 1, 4, 2


def _say(rig, voice, start, end, *, source="mic"):
    """Send one phrase through the queue that the capture callback fills."""
    samples = np.asarray([voice], dtype=np.float32)
    rig.saved_audio[source, start, end] = np.full(round((end - start) * 16000), voice, np.float32)
    rig.session._queue.put(Phrase(source=source, start=start, end=end, samples=samples))
    rig.session._queue.join()


def _room_session(monkeypatch, tmp_path):
    return _make_session(monkeypatch, tmp_path, system=False, diarize_mic=True)


def _ids(session):
    return [line.speaker_id for line in session.lines]


def _say_a_then_b_to_first_pass(rig):
    """Voice A speaks for 20 s and voice B for 10 s. The last phrase reaches 30 s."""
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 29.0)
    _say(rig, VOICE_B, 29.0, 30.0)


def test_a_new_voice_creates_no_speaker_until_a_pass_runs(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)

    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 29.0)

    assert _ids(rig.session) == ["room-1", "room-1"]
    assert rig.session.speakers == (("room-1", "Room 1"),)

    _say(rig, VOICE_B, 29.0, 30.0)

    assert _ids(rig.session) == ["room-1", "room-2", "room-2"]
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Room 2"))
    assert rig.session.failed_phrase_count == 0
    rig.session.stop()


def test_a_phrase_between_passes_joins_the_nearest_speaker(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_a_then_b_to_first_pass(rig)

    _say(rig, VOICE_B, 30.0, 32.0)
    _say(rig, VOICE_A, 32.0, 34.0)
    _say(rig, VOICE_C, 34.0, 36.0)

    assert _ids(rig.session)[3:5] == ["room-2", "room-1"]
    assert {speaker_id for speaker_id, _label in rig.session.speakers} == {"room-1", "room-2"}
    rig.session.stop()


def test_the_next_pass_waits_thirty_seconds_after_the_last_pass(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_a_then_b_to_first_pass(rig)

    _say(rig, VOICE_C, 30.0, 59.0)

    assert len(rig.session.speakers) == 2

    _say(rig, VOICE_C, 59.0, 60.0)

    assert ("room-3", "Room 3") in rig.session.speakers
    rig.session.stop()


def test_each_diarized_source_has_its_own_passes(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)

    _say_a_then_b_to_first_pass(rig)
    _say(rig, VOICE_A, 0.0, 20.0, source="system")
    _say(rig, VOICE_B, 20.0, 29.0, source="system")

    assert rig.session.speakers == (
        ("speaker-1", "Speaker 1"),
        ("room-1", "Room 1"),
        ("room-2", "Room 2"),
    )

    _say(rig, VOICE_B, 29.0, 30.0, source="system")

    assert rig.session.speakers == (
        ("speaker-1", "Speaker 1"),
        ("speaker-2", "Speaker 2"),
        ("room-1", "Room 1"),
        ("room-2", "Room 2"),
    )
    rig.session.stop()


def _say_until_voice_a_merges_into_voice_b(rig):
    """Voice A has 18 s of brief phrases, then voice B passes five times that speech."""
    for number in range(12):
        _say(rig, VOICE_A, number * 1.5, (number + 1) * 1.5)
    _say(rig, VOICE_B, 18.0, 30.0)
    _say(rig, VOICE_B, 30.0, 60.0)
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Room 2"))
    _say(rig, VOICE_B, 60.0, 110.0)


def test_a_speaker_keeps_its_number_when_an_earlier_speaker_merges_away(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)

    _say_until_voice_a_merges_into_voice_b(rig)

    # The batch pass alone numbers this one cluster 1, by first appearance.
    assert rig.session.speakers == (("room-2", "Room 2"),)
    assert set(_ids(rig.session)) == {"room-2"}
    rig.session.stop()


def _say_to_numbers_two_and_three(rig):
    """Leave room-2 for voice B and room-3 for voice C. Number 1 has merged away."""
    _say_until_voice_a_merges_into_voice_b(rig)
    _say(rig, VOICE_C, 110.0, 140.0)
    assert rig.session.speakers == (("room-2", "Room 2"), ("room-3", "Room 3"))


def test_save_numbers_speakers_from_one_by_first_appearance(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)

    rig.session.stop()

    expected = [("room-1", "Room 1")] * 15 + [("room-2", "Room 2")]
    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert detail.revision == "transcript.r2.jsonl"
    assert [(line.speaker_id, line.label) for line in detail.lines] == expected
    assert [(line.speaker_id, line.label) for line in rig.session.lines] == expected
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Room 2"))


def test_a_given_name_stays_when_save_changes_the_number(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)
    rig.session.rename("room-3", "Cara")

    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert [(line.speaker_id, line.label) for line in detail.lines][-2:] == [
        ("room-1", "Room 1"),
        ("room-2", "Cara"),
    ]
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Cara"))


def test_a_rename_on_the_saved_session_uses_the_saved_numbers(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)
    rig.session.stop()
    store = SessionStore(rig.writer.path.parent)
    speaker_id, _label = rig.session.speakers[1]

    store.rename_speaker(rig.writer.path.name, speaker_id, "Cara")

    detail = store.read(rig.writer.path.name)
    assert [(line.speaker_id, line.label) for line in detail.lines][-2:] == [
        ("room-1", "Room 1"),
        ("room-2", "Cara"),
    ]


def test_a_live_rename_after_the_save_changes_no_line(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)
    rig.session.stop()
    lines = rig.session.lines

    with pytest.raises(RuntimeError):
        rig.session.rename("room-2", "Cara")

    assert rig.session.lines == lines


def test_each_source_is_numbered_from_one_at_save(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    _say_to_numbers_two_and_three(rig)
    _say(rig, VOICE_A, 0.0, 30.0, source="system")

    rig.session.stop()

    assert set(rig.session.speakers) == {
        ("speaker-1", "Speaker 1"),
        ("room-1", "Room 1"),
        ("room-2", "Room 2"),
    }


def _saved(rig):
    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    return detail, [(line.speaker_id, line.label) for line in detail.lines]


def _shown(rig):
    return [(line.speaker_id, line.label) for line in rig.session.lines]


def test_a_later_voice_does_not_take_a_renamed_speaker_at_a_pass(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 20.0, 30.0)
    rig.session.rename("room-1", "Dana")
    _say(rig, VOICE_B, 30.0, 59.0)
    _say(rig, VOICE_B, 59.0, 60.0)

    expected = [("room-1", "Dana"), ("room-2", "Room 2"), ("room-2", "Room 2")]
    assert _shown(rig) == expected
    rig.session.stop()
    assert _saved(rig)[1] == expected


def test_a_later_voice_does_not_take_a_renamed_speaker_at_the_end_pass(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 20.0, 30.0)
    rig.session.rename("room-1", "Dana")
    _say(rig, VOICE_B, 30.0, 55.0)

    rig.session.stop()

    expected = [("room-1", "Dana"), ("room-2", "Room 2")]
    assert _saved(rig)[1] == expected
    assert _shown(rig) == expected


def test_the_first_phrase_keeps_its_speaker_at_the_first_pass(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 8.0)
    rig.session.rename("room-1", "Dana")
    _say(rig, VOICE_B, 8.0, 30.0)

    assert _shown(rig) == [("room-1", "Dana"), ("room-2", "Room 2")]
    rig.session.stop()


def test_the_first_phrase_keeps_number_one_with_no_given_name(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 8.0)
    _say(rig, VOICE_B, 8.0, 30.0)

    assert _shown(rig) == [("room-1", "Room 1"), ("room-2", "Room 2")]
    rig.session.stop()


def _say_ann_and_bob(rig):
    """A pass splits two voices that were first written as one speaker, and both get names."""
    _say(rig, VOICE_A, 0.0, 15.0)
    _say(rig, VOICE_B, 15.0, 30.0)
    rig.session.rename("room-1", "Ann")
    rig.session.rename("room-2", "Bob")


ANN_AND_BOB = [("room-1", "Ann"), ("room-2", "Bob")]


def test_a_skipped_end_pass_saves_the_names_on_screen(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)

    rig.session.skip_relabel()
    rig.session.stop()

    detail, saved = _saved(rig)
    assert detail.revision == "transcript.r2.jsonl"
    assert saved == ANN_AND_BOB
    assert _shown(rig) == ANN_AND_BOB
    assert rig.session.speakers == tuple(ANN_AND_BOB)
    assert rig.session.relabel_status == "Relabeling skipped"


def test_a_skip_during_the_end_pass_saves_the_names_on_screen(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    holder = {}
    original_relabel = live_session.relabel_system_lines

    def skip_in_end_pass(lines, embeddings, **kwargs):
        if "progress" in kwargs:
            holder["session"].skip_relabel()
            return None
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(voice_split, "relabel_system_lines", skip_in_end_pass)
    rig = _room_session(monkeypatch, tmp_path)
    holder["session"] = rig.session
    _say_ann_and_bob(rig)

    rig.session.stop()

    assert _saved(rig)[1] == ANN_AND_BOB
    assert rig.session.relabel_status == "Relabeling skipped"


def test_a_skipped_end_pass_numbers_the_saved_speakers_from_one(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)
    rig.session.rename("room-3", "Cara")

    rig.session.skip_relabel()
    rig.session.stop()

    expected = [("room-1", "Room 1")] * 15 + [("room-2", "Cara")]
    assert _saved(rig)[1] == expected
    assert _shown(rig) == expected
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Cara"))

    store = SessionStore(rig.writer.path.parent)
    store.rename_speaker(rig.writer.path.name, "room-1", "Ben")
    assert _saved(rig)[1] == [("room-1", "Ben")] * 15 + [("room-2", "Cara")]


def test_a_skip_keeps_the_you_lines_of_a_microphone_without_diarization(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 2.0)
    _say(rig, VOICE_A, 0.0, 15.0, source="system")
    _say(rig, VOICE_B, 15.0, 30.0, source="system")

    rig.session.skip_relabel()
    rig.session.stop()

    assert _saved(rig)[1] == [
        ("you", "You"),
        ("speaker-1", "Speaker 1"),
        ("speaker-2", "Speaker 2"),
    ]


def test_a_failed_end_pass_saves_the_names_on_screen(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines

    def fail_in_end_pass(lines, embeddings, **kwargs):
        if "progress" in kwargs:
            raise RuntimeError("batch clustering unavailable")
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(voice_split, "relabel_system_lines", fail_in_end_pass)
    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)

    rig.session.stop()

    detail, saved = _saved(rig)
    assert rig.session.relabel_error == "batch clustering unavailable"
    assert detail.revision == "transcript.r2.jsonl"
    assert saved == ANN_AND_BOB
    assert rig.session.speakers == tuple(ANN_AND_BOB)


def test_a_failed_revision_write_of_the_end_pass_saves_the_names_on_screen(monkeypatch, tmp_path):
    original_write = SessionStore.write_revision
    calls = []

    def fail_once(self, *args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise OSError("disk full")
        return original_write(self, *args, **kwargs)

    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)
    monkeypatch.setattr(SessionStore, "write_revision", fail_once)

    rig.session.stop()

    assert rig.session.relabel_error == "disk full"
    assert _saved(rig)[1] == ANN_AND_BOB


@pytest.mark.parametrize("skip", [True, False])
def test_a_failed_write_of_the_names_on_screen_fails_the_stop(monkeypatch, tmp_path, skip):
    def fail(self, *_args, **_kwargs):
        raise OSError("disk full")

    rig = _room_session(monkeypatch, tmp_path)
    _say_to_numbers_two_and_three(rig)
    monkeypatch.setattr(SessionStore, "write_revision", fail)
    if skip:
        rig.session.skip_relabel()
    lines = rig.session.lines

    with pytest.raises(OSError, match="disk full"):
        rig.session.stop()

    assert rig.session.lines == lines
    assert rig.worker.stopped
    assert rig.session.relabel_progress is None


def test_a_new_person_does_not_reuse_the_number_of_a_merged_speaker(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_until_voice_a_merges_into_voice_b(rig)

    _say(rig, VOICE_C, 110.0, 140.0)

    assert rig.session.speakers == (("room-2", "Room 2"), ("room-3", "Room 3"))
    rig.session.stop()


def test_a_rename_survives_passes_and_reaches_the_final_revision(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_a_then_b_to_first_pass(rig)

    rig.session.rename("room-2", "Dana")
    _say(rig, VOICE_B, 30.0, 45.0)
    _say(rig, VOICE_A, 45.0, 60.0)
    _say(rig, VOICE_B, 60.0, 90.0)

    assert ("room-2", "Dana") in rig.session.speakers
    assert ("room-1", "Room 1") in rig.session.speakers
    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert detail.revision == "transcript.r2.jsonl"
    assert [(line.speaker_id, line.label) for line in detail.lines] == [
        ("room-1", "Room 1"),
        ("room-2", "Dana"),
        ("room-2", "Dana"),
        ("room-2", "Dana"),
        ("room-1", "Room 1"),
        ("room-2", "Dana"),
    ]


def test_two_speakers_with_one_given_name_both_keep_it(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_a_then_b_to_first_pass(rig)
    rig.session.rename("room-1", "Guest")
    rig.session.rename("room-2", "Guest")

    _say(rig, VOICE_B, 30.0, 60.0)
    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert {(line.speaker_id, line.label) for line in detail.lines} == {
        ("room-1", "Guest"),
        ("room-2", "Guest"),
    }


def test_a_rename_of_a_merged_speaker_goes_to_the_speaker_that_holds_its_lines(
    monkeypatch, tmp_path
):
    rig = _room_session(monkeypatch, tmp_path)
    _say_until_voice_a_merges_into_voice_b(rig)

    # The rename dialog listed room-1 before the pass merged it.
    rig.session.rename("room-1", "Dana")

    assert rig.session.speakers == (("room-2", "Dana"),)
    assert {line.label for line in rig.session.lines} == {"Dana"}
    assert rig.writer.renames == [{"room-2": "Dana"}]
    rig.session.stop()


def test_a_rename_during_a_pass_is_kept(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines
    holder = {}

    def rename_during_pass(lines, embeddings, **kwargs):
        if "progress" not in kwargs:
            holder["session"].rename("room-1", "Dana")
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(live_session, "relabel_system_lines", rename_during_pass)
    rig = _room_session(monkeypatch, tmp_path)
    holder["session"] = rig.session

    _say_a_then_b_to_first_pass(rig)

    assert rig.session.speakers == (("room-1", "Dana"), ("room-2", "Room 2"))
    assert [line.label for line in rig.session.lines] == ["Dana", "Room 2", "Room 2"]
    rig.session.stop()


def test_a_mic_block_is_accepted_while_a_pass_runs(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines
    accepted = []
    holder = {}

    def probe_lock(lines, embeddings, **kwargs):
        if "progress" not in kwargs:
            block = Thread(target=holder["rig"].recorder.emit, args=(3,), daemon=True)
            block.start()
            block.join(timeout=0.5)
            accepted.append(not block.is_alive())
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(live_session, "relabel_system_lines", probe_lock)
    rig = _room_session(monkeypatch, tmp_path)
    holder["rig"] = rig

    _say_a_then_b_to_first_pass(rig)

    assert accepted == [True]
    rig.session.stop()


def test_speakers_lists_no_speaker_without_lines(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    append_line = rig.writer.append_line

    def fail_once(line):
        rig.writer.append_line = append_line
        raise OSError("disk full")

    rig.writer.append_line = fail_once
    _say(rig, VOICE_A, 0.0, 2.0)

    # The tracker made a speaker for this phrase, and the phrase has no line.
    assert rig.session.failed_phrase_count == 1
    assert rig.session.speakers == ()
    rig.session.stop()
    assert rig.session.speakers == ()


def test_speakers_after_the_end_pass_are_the_speakers_of_the_saved_lines(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    for number in range(8):
        _say(rig, VOICE_A, number * 1.5, (number + 1) * 1.5)
    _say(rig, VOICE_B, 12.0, 30.0)
    _say(rig, VOICE_B, 30.0, 60.0)
    # Voice A falls below one fifth of voice B here, and only the end pass sees it.
    _say(rig, VOICE_B, 60.0, 89.0)
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Room 2"))

    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    assert {(line.speaker_id, line.label) for line in detail.lines} == {("room-1", "Room 1")}
    assert rig.session.speakers == (("room-1", "Room 1"),)


def test_the_end_pass_makes_the_same_groups_as_the_batch_pass_alone(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_until_voice_a_merges_into_voice_b(rig)
    _say(rig, VOICE_A, 110.0, 125.0)
    _say(rig, VOICE_C, 125.0, 145.0)

    rig.session.stop()

    detail = SessionStore(rig.writer.path.parent).read(rig.writer.path.name)
    voices = ["A"] * 12 + ["B"] * 3 + ["A", "C"]
    groups = {}
    for voice, line in zip(voices, detail.lines, strict=True):
        groups.setdefault(line.speaker_id, set()).add(voice)
    # Voice A has 33 s and voice C has 20 s. Each is over one fifth of the 92 s of voice B.
    assert sorted(sorted(group) for group in groups.values()) == [["A"], ["B"], ["C"]]


def _saved_state(rig):
    summaries = SessionStore(rig.writer.path.parent).list_sessions()
    metadata = json.loads((rig.writer.path / "session.json").read_text())
    return metadata["method"], summaries[0].label_state


def test_a_finished_end_pass_saves_as_relabeled(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)

    rig.session.stop()

    assert _saved_state(rig) == ("diarization", "relabeled")


def test_a_skipped_end_pass_saves_as_live_labels(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)

    rig.session.skip_relabel()
    rig.session.stop()

    assert _saved_state(rig) == ("live", "live")


def test_a_failed_end_pass_saves_as_live_labels(monkeypatch, tmp_path):
    import stenographer.lib.live.live_session as live_session

    original_relabel = live_session.relabel_system_lines

    def fail_in_end_pass(lines, embeddings, **kwargs):
        if "progress" in kwargs:
            raise RuntimeError("batch clustering unavailable")
        return original_relabel(lines, embeddings, **kwargs)

    monkeypatch.setattr(voice_split, "relabel_system_lines", fail_in_end_pass)
    rig = _room_session(monkeypatch, tmp_path)
    _say_ann_and_bob(rig)

    rig.session.stop()

    assert _saved_state(rig) == ("live", "live")


def test_a_failed_rename_write_leaves_the_old_name_everywhere(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say_a_then_b_to_first_pass(rig)
    relabel = rig.writer.relabel

    def fail(_labels):
        raise OSError("disk full")

    rig.writer.relabel = fail
    with pytest.raises(OSError, match="disk full"):
        rig.session.rename("room-1", "Dana")
    rig.writer.relabel = relabel

    assert ("room-1", "Room 1") in rig.session.speakers
    # The next pass and the save read the name from the tracker.
    _say(rig, VOICE_B, 30.0, 60.0)
    assert ("room-1", "Room 1") in rig.session.speakers
    rig.session.stop()
    assert {label for _speaker_id, label in _saved(rig)[1]} == {"Room 1", "Room 2"}


def test_a_refused_rename_writes_no_record(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 2.0)

    with pytest.raises(ValueError):
        rig.session.rename("room-1", "   ")
    with pytest.raises(ValueError):
        rig.session.rename("room-9", "Dana")

    assert rig.writer.renames == []
    rig.session.stop()


def test_a_rename_write_stores_the_trimmed_name(monkeypatch, tmp_path):
    rig = _room_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 2.0)

    rig.session.rename("room-1", "  Dana ")

    assert rig.writer.renames == [{"room-1": "Dana"}]
    assert rig.session.speakers == (("room-1", "Dana"),)
    rig.session.stop()


class MainVoiceTracker(VoiceSpeakerTracker):
    """Take the voice of a slice of saved audio from most of its samples."""

    def embed(self, samples):
        return super().embed(np.asarray([np.median(samples)]))


def _split_session(monkeypatch, tmp_path):
    rig = _make_session(
        monkeypatch, tmp_path, system=False, diarize_mic=True, tracker=MainVoiceTracker
    )
    monkeypatch.setattr(voice_split, "find_speech_pieces", level_pieces)
    transcribe = rig.worker.transcribe
    rig.worker.transcribe = lambda samples: transcribe(np.asarray([np.median(samples)]))
    return rig


def _say_with_a_voice_change(rig, voice, other, start):
    """Send a 24 s phrase that changes from *voice* to *other* after 12.75 s."""
    _say(rig, voice, start, start + 24.0)
    rig.saved_audio["mic", start, start + 24.0] = np.concatenate(
        (np.full(204000, voice, np.float32), np.full(180000, other, np.float32))
    )


def _saved_detail(rig):
    return SessionStore(rig.writer.path.parent).read(rig.writer.path.name)


def test_the_end_pass_splits_a_voice_change_and_saves_each_part_with_its_speaker(
    monkeypatch, tmp_path
):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 40.0)
    _say_with_a_voice_change(rig, VOICE_A, VOICE_B, 40.0)

    rig.session.stop()

    detail = _saved_detail(rig)
    assert _saved_state(rig) == ("diarization", "relabeled")
    assert [line.speaker_id for line in detail.lines] == ["room-1", "room-2", "room-1", "room-2"]
    assert [line.label for line in detail.lines] == ["Room 1", "Room 2", "Room 1", "Room 2"]
    assert [line.text for line in detail.lines] == [
        "spoken words",
        "a phrase",
        "spoken words",
        "a phrase",
    ]
    first, second = detail.lines[2:]
    assert (first.start, second.end) == (40.0, 64.0)
    assert first.end == second.start
    assert 52.0 <= second.start <= 53.5
    assert first.wall < second.wall
    assert rig.session.lines == tuple(detail.lines)
    assert rig.session.speakers == (("room-1", "Room 1"), ("room-2", "Room 2"))
    assert "release" in rig.worker.events


def test_a_skip_reaches_the_speech_pass_of_a_recording(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    saw_the_skip = []

    def pass_until_the_skip(_samples, _model, *, progress, should_cancel):
        progress(0.1)
        rig.session.skip_relabel()
        saw_the_skip.append(wait_until(should_cancel, timeout=2))
        return None

    monkeypatch.setattr(voice_split, "find_speech_pieces", pass_until_the_skip)

    rig.session.stop()

    assert saw_the_skip == [True]
    assert rig.session.relabel_status == "Relabeling skipped"
    assert len(_saved_detail(rig).lines) == 1


def test_a_skip_while_a_part_decodes_saves_the_whole_phrase_as_live(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 40.0)
    _say_with_a_voice_change(rig, VOICE_A, VOICE_B, 40.0)
    transcribe = rig.worker.transcribe

    def skip_during_decode(samples):
        rig.session.skip_relabel()
        return transcribe(samples)

    rig.worker.transcribe = skip_during_decode

    rig.session.stop()

    detail = _saved_detail(rig)
    assert rig.session.relabel_status == "Relabeling skipped"
    assert _saved_state(rig) == ("live", "live")
    assert len(detail.lines) == 3
    assert (detail.lines[2].start, detail.lines[2].end) == (40.0, 64.0)


def test_a_source_whose_audio_failed_is_grouped_but_not_split(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 40.0)
    _say_with_a_voice_change(rig, VOICE_A, VOICE_B, 40.0)

    def no_pass(*_args, **_options):
        raise AssertionError("a source whose audio failed runs no pass")

    monkeypatch.setattr(voice_split, "find_speech_pieces", no_pass)
    rig.session._mark_audio_failed("mic", OSError("disk full"))

    rig.session.stop()

    detail = _saved_detail(rig)
    assert _saved_state(rig) == ("diarization", "relabeled")
    assert [line.speaker_id for line in detail.lines] == ["room-1", "room-2", "room-1"]


def test_a_given_name_stays_with_its_speech_when_an_earlier_phrase_split(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say_with_a_voice_change(rig, VOICE_A, VOICE_B, 0.0)
    _say(rig, VOICE_A, 24.0, 29.0)
    # This phrase passes 30 s, so a pass groups the three phrases and Bob's speaker appears.
    _say(rig, VOICE_B, 29.0, 59.0)
    bob = rig.session.lines[2].speaker_id
    rig.session.rename(bob, "Bob")

    rig.session.stop()

    detail = _saved_detail(rig)
    assert [(line.start, line.label) for line in detail.lines][-1] == (29.0, "Bob")
    assert len(detail.lines) == 4
    assert detail.lines[1].label == "Bob"


def test_end_pass_progress_stays_within_its_total_through_a_split(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 40.0)
    _say_with_a_voice_change(rig, VOICE_A, VOICE_B, 40.0)
    observed = []
    set_progress = rig.session._set_relabel_progress

    def observe(done, total):
        set_progress(done, total)
        observed.append(rig.session.relabel_progress)

    rig.session._set_relabel_progress = observe

    rig.session.stop()

    done = [value for value, _total in observed]
    assert done == sorted(done)
    assert {total for _done, total in observed} == {3}
    assert observed[-1] == (3, 3)


def test_a_speaker_model_error_on_a_piece_saves_the_names_on_screen(monkeypatch, tmp_path):
    rig = _split_session(monkeypatch, tmp_path)
    _say(rig, VOICE_A, 0.0, 20.0)
    _say(rig, VOICE_B, 20.0, 40.0)

    def fail(_samples):
        raise RuntimeError("Where node failed")

    rig.session._trackers["mic"].embed = fail

    rig.session.stop()

    detail = _saved_detail(rig)
    assert _saved_state(rig) == ("live", "live")
    assert rig.session.relabel_status.startswith("Relabel")
    assert len(detail.lines) == 2
