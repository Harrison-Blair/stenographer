# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for saved-session playback and revision jobs."""

from __future__ import annotations

import queue
import shutil
import threading
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stenographer.cli.hub.services import HubServices
from stenographer.lib.config.models import Config
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.errors import SpeakerDiarizerError
from stenographer.lib.platform.speaker_diarizer import SpeakerSegment
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionSourceError, StaleRevisionError
from stenographer.lib.sessions.jobs import SessionJobs
from stenographer.lib.transcribe.results import TranscriptionResult
from tests.lib.platform.support import NullProcessCounters

ONE_SPEAKER = (SpeakerSegment(0, 0.0, 1e9),)


class FakeDiarizer:
    """Give every file the same segments; ``reason`` makes it unavailable."""

    def __init__(self, segments=ONE_SPEAKER, reason=None):
        self.segments = tuple(segments)
        self.reason = reason
        self.files = []
        self.closed = False

    def unavailable_reason(self):
        return self.reason

    def diarize_file(self, source, **_options):
        self.files.append(source)
        return self.segments

    def close(self):
        self.closed = True


class FakePlatform:
    def __init__(self, data_dir, diarizer=None):
        self._data_dir = data_dir
        self.diarizer = diarizer if diarizer is not None else FakeDiarizer()

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"

    def speaker_diarizer(self):
        return self.diarizer

    def process_counters(self):
        return NullProcessCounters()


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
        self.returncode = 0
        self.finished = threading.Event()

    def poll(self):
        return self.returncode if self.finished.is_set() else None

    def terminate(self):
        self.terminated = True
        self.finished.set()

    def wait(self):
        self.finished.wait()
        return self.returncode


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


def test_rediarize_keeps_a_given_name_and_saves_a_revision(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    store = SessionStore(sessions_root)
    store.rename_speaker(session.name, "speaker-1", "Alex")
    platform = FakePlatform(tmp_path)
    jobs = SessionJobs(
        store,
        Config.defaults(),
        platform,
        worker_factory=lambda *_args, **_kwargs: FakeWorker(),
    )

    revision = jobs.rediarize(session.name)

    detail = store.read(session.name)
    assert revision == "transcript.r3.jsonl"
    assert detail.revision == revision
    assert [(line.source, line.label) for line in detail.lines] == [
        ("system", "Alex"),
        ("mic", "You"),
    ]
    assert platform.diarizer.files == [session / "system.flac"]
    assert platform.diarizer.closed
    assert (session / "transcript.jsonl").is_file()


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


def _jobs(tmp_path, store, diarizer=None):
    return SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path, diarizer),
        worker_factory=lambda *_args, **_kwargs: FakeWorker(),
    )


# Speaker 0 holds the first 4.5 s of each source, speaker 1 the rest.
TWO_TURNS = (SpeakerSegment(0, 0.0, 4.5), SpeakerSegment(1, 4.5, 12.0))


def test_rediarize_labels_mic_lines_as_room_speakers_when_the_session_was_diarized(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_room_session(sessions_root, diarized=True)
    store = SessionStore(sessions_root)

    _jobs(tmp_path, store, FakeDiarizer(TWO_TURNS)).rediarize(session.name)

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
    diarizer = FakeDiarizer(TWO_TURNS)

    _jobs(tmp_path, store, diarizer).rediarize(session.name)

    detail = store.read(session.name)
    assert [(line.source, line.label) for line in detail.lines] == [
        ("system", "Speaker 1"),
        ("mic", "You"),
        ("mic", "You"),
        ("mic", "You"),
    ]
    assert diarizer.files == [session / "system.flac"]


def test_rediarize_cuts_a_line_where_the_speaker_changes_and_decodes_each_part(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_room_session(sessions_root, diarized=True)
    store = SessionStore(sessions_root)
    segments = (SpeakerSegment(0, 0.0, 3.0), SpeakerSegment(1, 3.0, 12.0))

    _jobs(tmp_path, store, FakeDiarizer(segments)).rediarize(session.name)

    mic = [line for line in store.read(session.name).lines if line.source == "mic"]
    assert [(line.start, line.end, line.label, line.text) for line in mic] == [
        (2.0, 3.0, "Room 1", "new phrase 1"),
        (3.0, 4.5, "Room 2", "new phrase 2"),
        (5.0, 7.5, "Room 2", "fixture line"),
        (8.0, 10.5, "Room 2", "fixture line"),
    ]


def test_rediarize_without_speaker_separation_fails_and_saves_nothing(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(sessions_root)
    store = SessionStore(sessions_root)
    diarizer = FakeDiarizer(reason="speaker separation needs an AVX2 CPU")

    with pytest.raises(SpeakerDiarizerError, match="AVX2"):
        _jobs(tmp_path, store, diarizer).rediarize(session.name)

    assert store.read(session.name).revision == "transcript.jsonl"


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
    # The mic line is decoded first; the system line is decoded with its speaker pass.
    assert [(line.label, line.text) for line in detail.lines] == [
        ("Speaker 1", "new phrase 2"),
        ("You", "new phrase 1"),
    ]
    assert worker_configs == [(config.asr, "fake-transport")]
    assert workers[0].calls == 2
    assert workers[0].closed
    assert (session / "transcript.jsonl").is_file()


def test_retranscribe_without_speaker_separation_keeps_the_speakers(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_room_session(sessions_root, diarized=True)
    store = SessionStore(sessions_root)
    diarizer = FakeDiarizer(TWO_TURNS, reason="speaker separation needs an AVX2 CPU")

    _jobs(tmp_path, store, diarizer).retranscribe(session.name)

    detail = store.read(session.name)
    assert [(line.speaker_id, line.text) for line in detail.lines] == [
        ("speaker-1", "new phrase 1"),
        ("room-1", "new phrase 2"),
        ("room-1", "new phrase 3"),
        ("room-1", "new phrase 4"),
    ]
    assert diarizer.files == []


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


def _two_session_services(tmp_path):
    """Return services with a first and a second saved session, and each started player."""
    sessions_root = tmp_path / "sessions"
    first = _write_session(sessions_root)
    second = sessions_root / "20261020T011219Z"
    shutil.copytree(first, second)
    players = []

    def start_player(command):
        players.append(FakePlayer())
        return players[-1]

    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(sessions_root),
        player_factory=start_player,
    )
    return services, first.name, second.name, players


def test_playback_of_another_session_stops_the_first_and_starts_in_one_press(tmp_path):
    services, first, second, players = _two_session_services(tmp_path)

    services.toggle_session_playback(first)
    services.toggle_session_playback(second)

    assert len(players) == 2
    assert players[0].terminated
    assert not players[1].terminated

    # The same session still toggles: its second press stops it and starts nothing.
    services.toggle_session_playback(second)
    assert players[1].terminated
    assert len(players) == 2


def test_playback_reports_a_player_that_exits_with_an_error(tmp_path):
    session = _write_session(tmp_path / "sessions")
    player = FakePlayer()
    player.returncode = 3
    failures = queue.Queue()
    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
        player_factory=lambda _command: player,
    )

    services.toggle_session_playback(session.name, on_failure=failures.put)
    player.finished.set()

    assert failures.get(timeout=1) == 3


def test_playback_reports_a_crash_that_the_next_play_press_overtakes(tmp_path):
    class CrashedPlayer(FakePlayer):
        """The process has exited; its watcher has not returned from ``wait`` yet."""

        def poll(self):
            return 3

        def wait(self):
            self.finished.wait()
            return 3

    sessions_root = tmp_path / "sessions"
    first = _write_session(sessions_root)
    second = sessions_root / "20261020T011219Z"
    shutil.copytree(first, second)
    players = [CrashedPlayer(), FakePlayer()]
    remaining = iter(players)
    failures = queue.Queue()
    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(sessions_root),
        player_factory=lambda _command: next(remaining),
    )

    services.toggle_session_playback(first.name, on_failure=failures.put)
    services.toggle_session_playback(second.name, on_failure=failures.put)
    assert not players[0].terminated
    players[0].finished.set()

    assert failures.get(timeout=1) == 3
    services.stop_session_playback()


def test_playback_does_not_report_a_stop_or_a_clean_end(tmp_path):
    services, first, second, players = _two_session_services(tmp_path)
    failures = []

    # A stopped player exits with the signal status: the stop is not a failure.
    services.toggle_session_playback(first, on_failure=failures.append)
    players[0].returncode = -15
    services.stop_session_playback()
    assert players[0].finished.wait(timeout=1)

    # A player replaced by another session is a stop too.
    services.toggle_session_playback(first, on_failure=failures.append)
    players[1].returncode = -15
    services.toggle_session_playback(second, on_failure=failures.append)

    # A player that ends by itself with status zero is a clean end.
    players[2].finished.set()

    for thread in threading.enumerate():
        if thread.name == "stenographer-session-player":
            thread.join(timeout=1)
    assert failures == []


class RecordingDecoder:
    def __init__(self):
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        yield np.full(48_000, 0.1, dtype=np.float32)


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
    diarizer = FakeDiarizer((SpeakerSegment(0, 0.0, 1.2), SpeakerSegment(1, 1.2, 3.0)))

    def make_worker(_asr_config, *, transport):
        workers.append(FakeWorker())
        return workers[-1]

    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path, diarizer),
        worker_factory=make_worker,
        media_decoder=decoder,
    )

    revision = jobs.retranscribe(session_id)

    detail = store.read(session_id)
    assert revision == "transcript.r2.jsonl"
    # One decode of the source feeds both the speaker pass and the new text.
    assert decoder.paths == [sessions_root / session_id / "source.wav"]
    assert len(diarizer.files) == 1
    assert [(line.source, line.label, line.text) for line in detail.lines] == [
        ("file", "Speaker 1", "new phrase 1"),
        ("file", "Speaker 2", "new phrase 2"),
    ]
    assert detail.summary.kind == "file"
    assert workers[0].closed


class RampDecoder:
    """Decode a ramp whose sample values equal their positions, in small chunks."""

    def __init__(self, total=48_000, chunk_frames=3_000, error=None):
        self.total = total
        self.chunk_frames = chunk_frames
        self.error = error
        self.closed = False

    def __call__(self, _path):
        try:
            for start in range(0, self.total, self.chunk_frames):
                yield np.arange(start, min(self.total, start + self.chunk_frames), dtype=np.float32)
            if self.error is not None:
                raise self.error
        finally:
            self.closed = True


class RangeWorker:
    """Report the first and last sample value of each phrase."""

    def __init__(self, on_transcribe=None):
        self.on_transcribe = on_transcribe
        self.closed = False

    def transcribe(self, samples):
        if self.on_transcribe is not None:
            self.on_transcribe()
        return TranscriptionResult(f"{int(samples[0])}..{int(samples[-1])}", 1.0)

    def shutdown(self):
        self.closed = True


def _timed_file_session(sessions_root, tmp_path, intervals):
    source = tmp_path / "Interview.wav"
    sf.write(source, np.zeros(16, dtype=np.float32), 16_000)
    return SessionStore(sessions_root).create_file_session(
        source,
        started_at=datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
        duration_seconds=3.0,
        lines=[
            TranscriptLine(start, end, "", "file", "speaker-1", "Speaker 1", "old")
            for start, end in intervals
        ],
    )


def _ramp_jobs(tmp_path, store, decoder, worker):
    return SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path),
        worker_factory=lambda *_args, **_kwargs: worker,
        media_decoder=decoder,
    )


def test_retranscribe_file_session_reads_each_interval_across_chunks(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _timed_file_session(
        sessions_root,
        tmp_path,
        # Overlapping, without duration, and cut by the end of the audio.
        [(0.5, 1.5), (1.0, 2.0), (2.5, 2.5), (2.75, 99.0)],
    )
    store = SessionStore(sessions_root)
    decoder = RampDecoder()

    _ramp_jobs(tmp_path, store, decoder, RangeWorker()).retranscribe(session_id)

    assert [line.text for line in store.read(session_id).lines] == [
        "8000..23999",
        "16000..31999",
        "old",
        "44000..47999",
    ]
    assert decoder.closed


def test_retranscribe_file_session_holds_only_about_one_phrase_of_audio(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _timed_file_session(
        sessions_root, tmp_path, [(index * 0.25, index * 0.25 + 0.25) for index in range(120)]
    )
    jobs = _ramp_jobs(
        tmp_path,
        SessionStore(sessions_root),
        RampDecoder(total=480_000),
        RangeWorker(on_transcribe=lambda: held.append(tracemalloc.get_traced_memory()[0])),
    )
    held = []

    tracemalloc.start()
    try:
        jobs.retranscribe(session_id)
    finally:
        tracemalloc.stop()

    # All 480 000 samples take 1.9 MB. One 4 000 sample phrase and one chunk take 28 kB.
    assert len(held) == 120
    assert max(held) - held[0] < 200_000


def test_retranscribe_file_session_fails_for_a_phrase_past_the_decoded_audio(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _timed_file_session(sessions_root, tmp_path, [(0.0, 1.0), (3.5, 4.0)])
    store = SessionStore(sessions_root)
    worker = RangeWorker()
    decoder = RampDecoder()

    with pytest.raises(ValueError, match="has no audio"):
        _ramp_jobs(tmp_path, store, decoder, worker).retranscribe(session_id)

    assert store.read(session_id).revision == "transcript.jsonl"
    assert worker.closed
    assert decoder.closed


def test_retranscribe_file_session_fails_for_a_decode_error_after_the_last_line(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _timed_file_session(sessions_root, tmp_path, [(0.0, 0.5)])
    store = SessionStore(sessions_root)
    decoder = RampDecoder(error=RuntimeError("ffmpeg exited with status 1"))

    with pytest.raises(RuntimeError, match="status 1"):
        _ramp_jobs(tmp_path, store, decoder, RangeWorker()).retranscribe(session_id)

    assert store.read(session_id).revision == "transcript.jsonl"


def test_retranscribe_file_session_stops_the_decoder_when_the_worker_fails(tmp_path):
    sessions_root = tmp_path / "sessions"
    session_id = _timed_file_session(sessions_root, tmp_path, [(0.0, 0.5)])
    decoder = RampDecoder()

    def fail():
        raise RuntimeError("worker failed")

    jobs = _ramp_jobs(
        tmp_path, SessionStore(sessions_root), decoder, RangeWorker(on_transcribe=fail)
    )
    # The kept exception holds the job frames, so only an explicit close stops the decoder.
    with pytest.raises(RuntimeError) as caught:
        jobs.retranscribe(session_id)

    assert str(caught.value) == "worker failed"
    assert decoder.closed


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
        _jobs(tmp_path, store).rediarize(session_id)

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
    jobs = SessionJobs(
        store,
        Config.defaults(),
        FakePlatform(tmp_path),
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
