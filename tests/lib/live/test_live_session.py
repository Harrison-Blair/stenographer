# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-session coordination tests without audio hardware, ASR, or speaker processes."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from stenographer.lib.live.phrase_segmenter import Phrase
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.platform.errors import SpeakerDiarizerError
from stenographer.lib.platform.speaker_diarizer import SpeakerSegment
from stenographer.lib.sessions import SessionStore
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult
from tests.lib.platform.support import NullProcessCounters

RATE = 16000
# One speaker for the whole stream, unless a test says otherwise.
ALL_ONE_SPEAKER = SpeakerSegment(0, 0.0, 1e9)


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


class FakeStream:
    """A live speaker stream whose finals, final time, and overflow the test sets."""

    def __init__(self, source):
        self.source = source
        self.pushed_seconds = 0.0
        self.finals = [ALL_ONE_SPEAKER]
        # Segments still open at the live edge: start and speaker are fixed.
        self.tail = []
        self.final_until = float("inf")
        self.overflow = False
        self.poll_error = None
        self.closed = False
        self.finished = False

    def push(self, samples):
        self.pushed_seconds += samples.size / RATE

    def poll(self):
        if self.poll_error is not None:
            raise self.poll_error
        final = tuple(self.finals)
        self.finals.clear()
        return final, tuple(self.tail)

    def overflowed(self):
        return self.overflow

    def finish(self, _timeout):
        self.finished = True
        self.final_until = float("inf")
        final = tuple(self.finals)
        self.finals.clear()
        return final

    def close(self):
        self.closed = True


class FakeDiarizer:
    def __init__(self, reason=None, open_error=None, file_segments=()):
        self.reason = reason
        self.open_error = open_error
        self.file_segments = tuple(file_segments)
        self.streams = {}
        self.files = []
        self.closed = False

    def unavailable_reason(self):
        return self.reason

    def open_live(self, source):
        if self.open_error is not None:
            raise self.open_error
        stream = FakeStream(source)
        self.streams[source] = stream
        return stream

    def diarize_file(self, source, **_options):
        self.files.append(source)
        return self.file_segments

    def close(self):
        self.closed = True


class FakePlatform:
    def __init__(self, system_capture, data_path, diarizer, platform_error=None):
        self._system_capture = system_capture
        self._data_path = data_path
        self._diarizer = diarizer
        self._platform_error = platform_error

    def data_dir(self, _env, _home):
        return self._data_path

    def system_audio_capture(self):
        if self._platform_error is not None:
            raise self._platform_error
        return self._system_capture

    def asr_transport(self):
        return object()

    def speaker_diarizer(self):
        return self._diarizer

    def process_counters(self):
        return NullProcessCounters()


class FakeSegmenter:
    def __init__(self, source, _model_path, **_kwargs):
        self.source = source
        self.flushed = False
        self.speech_detected = False
        # ``(start, end, samples)`` of the phrases that the next block gives.
        self.script = []

    def accept(self, block):
        if self.script:
            script, self.script = self.script, []
            return [
                Phrase(source=self.source, start=start, end=end, samples=samples)
                for start, end, samples in script
            ]
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
    diarizer=None,
    **session_options,
):
    import stenographer.lib.live.live_session as live_session

    writer = FakeWriter()
    system_capture = FakeSystemCapture(*availability)
    diarizer = diarizer if diarizer is not None else FakeDiarizer()
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
    platform = FakePlatform(system_capture, tmp_path, diarizer, platform_error)
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
        diarizer=diarizer,
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


def test_live_session_exposes_its_worker_pids_and_idle_unload_deadline(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, start=False)
    rig.worker.process_ids = (4321,)
    rig.worker.idle_unload_deadline = 12.5

    assert rig.session.process_ids == (4321,)
    assert rig.session.idle_unload_deadline == 12.5


def _saved_detail(rig):
    return SessionStore(rig.writer.path.parent).read(rig.writer.path.name)


def _halves(first, second, seconds=2.0):
    """Samples whose first half decodes as *first* and second half as *second*."""
    half = round(seconds * RATE / 2)
    return np.concatenate((np.full(half, first, np.float32), np.full(half, second, np.float32)))


def _speak(rig, source, start, end, samples):
    """Make the next block of *source* give one phrase and wait for its lines."""
    segmenter = next(s for s in reversed(rig.segmenters) if s.source == source)
    segmenter.script.append((start, end, samples))
    (rig.system if source == "system" else rig.recorder).emit(1)
    rig.session._queue.join()


def test_a_speaker_change_cuts_a_phrase_into_one_line_per_speaker(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    rig.diarizer.streams["system"].finals = [
        SpeakerSegment(0, 0.0, 1.0),
        SpeakerSegment(1, 1.0, 2.0),
    ]

    _speak(rig, "system", 0.0, 2.0, _halves(1, 4))

    assert [(line.start, line.end, line.label, line.text) for line in rig.session.lines] == [
        (0.0, 1.0, "Speaker 1", "spoken words"),
        (1.0, 2.0, "Speaker 2", "a phrase"),
    ]
    # Each part is decoded once.
    assert rig.worker.calls == [1, 4]
    rig.session.stop()


def test_a_speaker_who_still_talks_labels_the_final_part_of_a_phrase(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    stream = rig.diarizer.streams["system"]
    stream.finals = [SpeakerSegment(0, 0.0, 1.0)]
    # Speaker 1 started at 1 s and still talks; frames up to 3 s are final.
    stream.tail = [SpeakerSegment(1, 1.0, 5.0)]
    stream.final_until = 3.0

    _speak(rig, "system", 0.0, 2.0, _halves(1, 4))

    assert [(line.start, line.end, line.label) for line in rig.session.lines] == [
        (0.0, 1.0, "Speaker 1"),
        (1.0, 2.0, "Speaker 2"),
    ]
    rig.session.stop()


def test_a_phrase_waits_until_its_speakers_are_final(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    stream = rig.diarizer.streams["system"]
    stream.final_until = 1.0

    _speak(rig, "system", 0.0, 2.0, np.full(2 * RATE, 1, np.float32))
    assert rig.session.lines == ()

    stream.final_until = 2.0
    rig.system.emit(3)
    rig.session._queue.join()
    assert [line.text for line in rig.session.lines] == ["spoken words"]
    rig.session.stop()


def test_stop_releases_the_phrases_that_still_wait_and_finishes_each_stream(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    stream = rig.diarizer.streams["system"]
    stream.final_until = float("-inf")
    rig.system.emit(1)
    assert rig.session.lines == ()

    rig.session.stop()

    assert stream.finished
    assert [line.label for line in rig.session.lines] == ["Speaker 1"]
    assert rig.diarizer.closed


def test_a_normal_stop_saves_the_live_labels_with_no_speaker_pass(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    rig.system.emit(1)

    rig.session.stop()

    assert rig.diarizer.files == []
    detail = _saved_detail(rig)
    assert detail.summary.label_state == "live"
    assert [(line.speaker_id, line.label) for line in detail.lines] == [("speaker-1", "Speaker 1")]


def test_speakers_are_numbered_by_first_line_and_sources_never_share_them(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    rig.diarizer.streams["system"].finals = [
        SpeakerSegment(3, 0.0, 1.0),
        SpeakerSegment(0, 1.0, 2.0),
    ]

    _speak(rig, "system", 0.0, 2.0, _halves(1, 4))
    _speak(rig, "mic", 0.0, 0.5, np.full(RATE // 2, 1, np.float32))
    rig.session.stop()

    assert [(line.source, line.speaker_id, line.label) for line in rig.writer.lines] == [
        ("system", "speaker-1", "Speaker 1"),
        ("system", "speaker-2", "Speaker 2"),
        ("mic", "room-1", "Room 1"),
    ]
    assert rig.session.speakers == (
        ("speaker-1", "Speaker 1"),
        ("speaker-2", "Speaker 2"),
        ("room-1", "Room 1"),
    )


def test_without_speaker_separation_lines_are_you_and_system(monkeypatch, tmp_path):
    reason = "speaker separation needs an AVX2 CPU"
    rig = _make_session(
        monkeypatch, tmp_path, diarize_mic=True, diarizer=FakeDiarizer(reason=reason)
    )
    rig.recorder.emit(1)
    rig.system.emit(4)
    rig.session._queue.join()

    assert rig.diarizer.streams == {}
    assert rig.session.speaker_issue == reason
    assert rig.session.speaker_notice == "no speaker labels"
    assert {(line.speaker_id, line.label) for line in rig.session.lines} == {
        ("you", "You"),
        ("system", "System"),
    }
    assert rig.session.speakers == ()
    rig.session.stop()
    assert rig.session.failed_phrase_count == 0


def test_a_helper_that_fails_to_start_gives_no_speaker_labels(monkeypatch, tmp_path):
    from stenographer.lib.platform.errors import SpeakerDiarizerError

    diarizer = FakeDiarizer(open_error=SpeakerDiarizerError("helper did not start"))
    rig = _make_session(monkeypatch, tmp_path, mic=False, diarizer=diarizer)
    rig.system.emit(1)
    rig.session._queue.join()

    assert rig.session.speaker_issue == "helper did not start"
    assert [line.label for line in rig.session.lines] == ["System"]
    rig.session.stop()


def test_a_failed_stream_gives_its_waiting_and_later_phrases_no_speaker(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    stream = rig.diarizer.streams["system"]
    stream.final_until = float("-inf")
    rig.system.emit(1)
    stream.poll_error = SpeakerDiarizerError("helper exited")
    rig.system.emit(4)
    rig.session._queue.join()

    assert [line.label for line in rig.session.lines] == ["System", "System"]
    assert stream.closed
    assert rig.session.speaker_notice == "no speaker labels"
    rig.session.stop()


def test_an_overflowed_stream_labels_its_source_from_the_saved_audio_at_stop(monkeypatch, tmp_path):
    clock = FakeClock()
    diarizer = FakeDiarizer(file_segments=[SpeakerSegment(0, 0.0, 2.0)])
    rig = _make_session(monkeypatch, tmp_path, clock=clock, diarize_mic=True, diarizer=diarizer)
    rig.diarizer.streams["system"].overflow = True
    rig.system.emit(1)
    rig.recorder.emit(1)
    rig.session._queue.join()

    assert rig.session.speaker_notice == "system speakers behind"
    assert {(line.source, line.label) for line in rig.session.lines} == {
        ("system", "System"),
        ("mic", "Room 1"),
    }
    assert rig.diarizer.streams["system"].closed
    clock.now = 2.0
    rig.session.stop()

    assert rig.diarizer.files == [rig.writer.path / "system.flac"]
    detail = _saved_detail(rig)
    assert detail.summary.label_state == "relabeled"
    assert {(line.source, line.label) for line in detail.lines} == {
        ("system", "Speaker 1"),
        ("mic", "Room 1"),
    }


def test_a_very_short_phrase_is_no_failure(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    rig.diarizer.streams["system"].finals = [
        SpeakerSegment(0, 0.0, 0.03),
        SpeakerSegment(1, 0.03, 0.05),
    ]

    _speak(rig, "system", 0.0, 0.05, _halves(1, 4, seconds=0.05))
    rig.session.stop()

    assert rig.session.failed_phrase_count == 0
    assert [line.label for line in rig.session.lines] == ["Speaker 1", "Speaker 2"]


def test_a_speaker_edge_a_hair_inside_a_phrase_makes_no_empty_part(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    # Float sums can put an edge a nanosecond past the phrase start: zero samples.
    rig.diarizer.streams["system"].finals = [
        SpeakerSegment(0, 0.0, 1e-9),
        SpeakerSegment(1, 1e-9, 1.0),
    ]

    _speak(rig, "system", 0.0, 0.5, np.full(RATE // 2, 1, np.float32))
    rig.session.stop()

    assert rig.session.failed_phrase_count == 0
    assert [line.text for line in rig.session.lines] == ["spoken words"]


def test_a_refused_rename_writes_no_record(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    rig.system.emit(1)
    rig.session._queue.join()

    with pytest.raises(ValueError):
        rig.session.rename("speaker-1", "   ")
    with pytest.raises(ValueError):
        rig.session.rename("speaker-9", "Dana")
    with pytest.raises(ValueError):
        rig.session.rename("system", "Dana")

    assert rig.writer.renames == []
    rig.session.stop()


def test_a_rename_stores_the_trimmed_name_for_later_lines_of_that_speaker(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, diarize_mic=True)
    rig.recorder.emit(1)
    rig.session._queue.join()

    rig.session.rename("room-1", "  Dana ")
    rig.recorder.emit(4)
    rig.session._queue.join()

    assert rig.writer.renames == [{"room-1": "Dana"}]
    assert [line.label for line in rig.session.lines] == ["Dana", "Dana"]
    assert rig.session.speakers == (("room-1", "Dana"),)
    rig.session.stop()


def test_a_failed_rename_write_leaves_the_old_name_everywhere(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path, mic=False)
    rig.system.emit(1)
    rig.session._queue.join()

    def fail(_labels):
        raise OSError("disk full")

    rig.writer.relabel = fail
    with pytest.raises(OSError, match="disk full"):
        rig.session.rename("speaker-1", "Dana")
    rig.system.emit(4)
    rig.session._queue.join()

    assert [line.label for line in rig.session.lines] == ["Speaker 1", "Speaker 1"]
    rig.session.stop()


def test_audio_pushed_after_a_pause_maps_to_session_time(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock, mic=False)
    stream = rig.diarizer.streams["system"]
    stream.finals = []
    rig.system.emit(3)
    clock.now = 1.0
    rig.session.toggle("system")
    clock.now = 5.0
    rig.session.toggle("system")
    # The stream heard one sample before the pause: its next second starts at session 5 s.
    stream.finals = [SpeakerSegment(0, 1 / RATE, 1 / RATE + 1.0)]
    _speak(rig, "system", 0.0, 1.0, np.full(RATE, 1, np.float32))

    assert [(line.start, line.label) for line in rig.session.lines] == [(5.0, "Speaker 1")]
    assert rig.session._segments["system"] == [SpeakerSegment(0, 5.0, 6.0)]
    rig.session.stop()
