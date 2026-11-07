# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-diarize and re-transcribe split saved phrases at voice changes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.config.models import Config
from stenographer.lib.live import voice_split
from stenographer.lib.live.models import SPEAKER_MODEL
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.jobs import SessionJobs
from stenographer.lib.transcribe.results import TranscriptionResult
from tests.lib.live.speech_support import level_pieces
from tests.lib.platform.support import NullProcessCounters

RATE = 16000
ANN, BOB = 0.1, 0.4


def voice_of(samples):
    return "ann" if abs(float(np.median(samples)) - ANN) < 0.05 else "bob"


class Tracker:
    """Give each stretch of audio the unit vector of its main level."""

    def __init__(self, _model_path):
        pass

    def embed(self, samples):
        return np.array([1.0, 0.0] if voice_of(samples) == "ann" else [0.0, 1.0], dtype=np.float32)


class Worker:
    instances = 0

    def __init__(self, _config, *, transport):
        assert transport == "transport"
        type(self).instances += 1
        self.closed = False
        self.calls = 0

    def transcribe(self, samples):
        self.calls += 1
        return TranscriptionResult(f"{voice_of(samples)} {samples.size / RATE:.0f}", 1.0)

    def shutdown(self):
        self.closed = True


class Platform:
    def __init__(self, data_dir):
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "transport"

    def process_counters(self):
        return NullProcessCounters()


def audio():
    """Ann for 20 s, Bob for 20 s, and a 24 s phrase that changes from Ann to Bob at 12.75 s."""
    return np.concatenate(
        (
            np.full(20 * RATE, ANN, np.float32),
            np.full(20 * RATE, BOB, np.float32),
            np.full(int(12.75 * RATE), ANN, np.float32),
            np.full(int(11.25 * RATE), BOB, np.float32),
        )
    )


WALL = "2026-10-20T01:12:{:02d}+00:00"


def recorded(root, source="system", speaker=("speaker-1", "Speaker 1"), *, diarized=False):
    writer = SessionWriter.open(root, datetime(2026, 10, 20, 1, 12, 0, tzinfo=UTC))
    if diarized:
        writer.mark_mic_diarized()
    writer.write_audio(source, audio())
    for start, end in ((0.0, 20.0), (20.0, 40.0), (40.0, 64.0)):
        wall = f"2026-10-20T01:12:{int(start):02d}+00:00"
        writer.append_line(TranscriptLine(start, end, wall, source, *speaker, "old text"))
    writer.close()
    return writer.path.name


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_split, "find_speech_pieces", level_pieces)
    model = tmp_path / "models" / "live" / SPEAKER_MODEL.filename
    model.parent.mkdir(parents=True)
    model.touch()
    store = SessionStore(tmp_path / "sessions")
    decoded = []

    def media_decoder(path):
        decoded.append(path)
        samples = audio()
        for start in range(0, samples.size, 65536):
            yield samples[start : start + 65536]

    jobs = SessionJobs(
        store,
        Config.defaults(),
        Platform(tmp_path),
        speaker_tracker_factory=Tracker,
        worker_factory=Worker,
        media_decoder=media_decoder,
    )
    Worker.instances = 0
    return SimpleNamespace(store=store, jobs=jobs, root=tmp_path, decoded=decoded, model=model)


def rows(detail):
    return [(line.speaker_id, line.text) for line in detail.lines]


def test_rediarize_splits_the_changing_phrase_and_keeps_other_text(rig):
    session = recorded(rig.root)

    revision = rig.jobs.rediarize(session)

    detail = rig.store.read(session)
    assert revision == "transcript.r2.jsonl"
    assert detail.summary.label_state == "relabeled"
    assert rows(detail)[:2] == [("speaker-1", "old text"), ("speaker-2", "old text")]
    # The Ann part runs to the cut and the Bob part from it, each under its own speaker.
    assert detail.lines[2].speaker_id == "speaker-1"
    assert detail.lines[2].text.startswith("ann")
    assert detail.lines[3].speaker_id == "speaker-2"
    assert detail.lines[3].text.startswith("bob")
    assert len(detail.lines) == 4
    assert detail.lines[2].start == 40.0
    assert detail.lines[2].end == detail.lines[3].start
    assert 52.0 <= detail.lines[3].start <= 53.5
    assert detail.lines[3].end == 64.0
    cut = int(detail.lines[3].start - 40.0)
    assert detail.lines[3].wall.startswith(f"2026-10-20T01:12:{40 + cut:02d}")


def test_rediarize_without_a_change_keeps_all_text(rig):
    session = recorded(rig.root)
    path = rig.root / "sessions" / session / "system.flac"
    samples = np.concatenate(
        (np.full(20 * RATE, ANN, np.float32), np.full(44 * RATE, BOB, np.float32))
    )
    sf.write(path, samples, RATE, format="FLAC", subtype="PCM_24")

    rig.jobs.rediarize(session)

    detail = rig.store.read(session)
    assert [text for _, text in rows(detail)] == ["old text"] * 3


def test_an_undiarized_mic_stays_you_and_is_not_split(rig):
    session = recorded(rig.root, "mic", ("you", "You"))

    rig.jobs.rediarize(session)

    detail = rig.store.read(session)
    assert rows(detail) == [("you", "old text")] * 3


def test_a_diarized_mic_splits_under_room_speakers(rig):
    session = recorded(rig.root, "mic", ("room-1", "Room 1"), diarized=True)

    rig.jobs.rediarize(session)

    detail = rig.store.read(session)
    assert [line.speaker_id for line in detail.lines] == ["room-1", "room-2", "room-1", "room-2"]
    assert [line.label for line in detail.lines] == ["Room 1", "Room 2", "Room 1", "Room 2"]


def test_rename_and_a_later_rediarize_work_on_a_split_session(rig):
    session = recorded(rig.root)
    rig.jobs.rediarize(session)
    split = rig.store.read(session)

    rig.store.rename_speaker(session, "speaker-2", "Bea")
    renamed = rig.store.read(session)
    assert [line.label for line in renamed.lines] == ["Speaker 1", "Bea", "Speaker 1", "Bea"]

    revision = rig.jobs.rediarize(session)

    again = rig.store.read(session)
    assert revision == "transcript.r4.jsonl"
    assert [(line.start, line.end, line.text) for line in again.lines] == [
        (line.start, line.end, line.text) for line in split.lines
    ]
    assert [line.label for line in again.lines] == ["Speaker 1", "Bea", "Speaker 1", "Bea"]


def test_every_revision_of_a_split_session_stays_readable(rig):
    session = recorded(rig.root)
    rig.jobs.rediarize(session)

    directory = rig.root / "sessions" / session
    assert (directory / "transcript.jsonl").is_file()
    assert (directory / "transcript.r2.md").read_text(encoding="utf-8").count("**") == 8
    assert not rig.store.read(session).summary.interrupted


def test_retranscribe_replaces_text_splits_and_groups_again(rig):
    session = recorded(rig.root)

    revision = rig.jobs.retranscribe(session)

    detail = rig.store.read(session)
    assert revision == "transcript.r2.jsonl"
    assert detail.summary.label_state == "re-transcribe"
    assert [line.text.split()[0] for line in detail.lines] == ["ann", "bob", "ann", "bob"]
    assert detail.lines[0].text == "ann 20"
    assert [line.speaker_id for line in detail.lines] == [
        "speaker-1",
        "speaker-2",
        "speaker-1",
        "speaker-2",
    ]


def test_retranscribe_carries_a_given_name_to_the_right_voice(rig):
    session = recorded(rig.root)
    rig.jobs.rediarize(session)
    rig.store.rename_speaker(session, "speaker-1", "Ann")

    rig.jobs.retranscribe(session)

    detail = rig.store.read(session)
    assert {(line.text.split()[0], line.label) for line in detail.lines} == {
        ("ann", "Ann"),
        # The existing rule gives an unnamed speaker the lowest free number.
        ("bob", "Speaker 1"),
    }


def test_retranscribe_keeps_an_undiarized_mic_and_needs_no_speaker_model(rig):
    session = recorded(rig.root, "mic", ("you", "You"))
    rig.model.unlink()

    rig.jobs.retranscribe(session)

    detail = rig.store.read(session)
    assert [(line.speaker_id, line.text.split()[0]) for line in detail.lines] == [
        ("you", "ann"),
        ("you", "bob"),
        ("you", "ann"),
    ]


def test_retranscribe_of_separated_lines_reports_a_missing_speaker_model(rig):
    session = recorded(rig.root)
    rig.model.unlink()

    with pytest.raises(FileNotFoundError, match="speaker model is missing"):
        rig.jobs.retranscribe(session)


def file_session(rig, speakers):
    source = rig.root / "Interview.wav"
    sf.write(source, audio(), RATE)
    return rig.store.create_file_session(
        source,
        started_at=datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
        duration_seconds=64.0,
        lines=[
            TranscriptLine(0.0, 20.0, "", "file", speakers[0], "Speaker 1", "old text"),
            TranscriptLine(20.0, 40.0, "", "file", speakers[1], "Speaker 2", "old text"),
            TranscriptLine(40.0, 64.0, "", "file", speakers[0], "Speaker 1", "old text"),
        ],
    )


def test_retranscribe_of_a_file_session_splits_with_a_second_decode(rig):
    session = file_session(rig, ("speaker-1", "speaker-2"))

    rig.jobs.retranscribe(session)

    detail = rig.store.read(session)
    assert [line.text.split()[0] for line in detail.lines] == ["ann", "bob", "ann", "bob"]
    assert [line.speaker_id for line in detail.lines] == [
        "speaker-1",
        "speaker-2",
        "speaker-1",
        "speaker-2",
    ]
    assert len(rig.decoded) == 2


def test_retranscribe_of_a_one_speaker_file_session_only_replaces_text(rig):
    session = file_session(rig, ("speaker-1", "speaker-1"))
    rig.model.unlink()

    rig.jobs.retranscribe(session)

    detail = rig.store.read(session)
    assert [line.text.split()[0] for line in detail.lines] == ["ann", "bob", "ann"]
    assert {line.speaker_id for line in detail.lines} == {"speaker-1"}
    assert len(rig.decoded) == 1


def _failed_file_session(rig):
    source = rig.root / "Interview.wav"
    sf.write(source, audio(), RATE)
    return rig.store.create_file_session(
        source,
        started_at=datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
        duration_seconds=64.0,
        lines=[
            TranscriptLine(0.0, 20.0, "", "file", "speaker-1", "Speaker 1", "old text"),
            TranscriptLine(20.0, 40.0, "", "file", "speaker-2", "Speaker 2", "old text"),
        ],
        speaker_pass_failed=True,
    )


def test_a_later_retranscribe_clears_the_mark_of_a_failed_pass(rig):
    session = _failed_file_session(rig)
    assert rig.store.read(session).summary.speaker_pass_failed

    rig.jobs.retranscribe(session)

    summary = rig.store.read(session).summary
    assert summary.label_state == "re-transcribe"
    assert not summary.speaker_pass_failed


def test_a_rename_keeps_the_key_and_shows_as_a_rename(rig):
    session = _failed_file_session(rig)

    rig.store.rename_speaker(session, "speaker-2", "Bea")

    metadata = json.loads((rig.root / "sessions" / session / "session.json").read_text())
    assert metadata["speaker_pass_failed"] is True
    assert metadata["source_name"] == "Interview.wav"
    summary = rig.store.read(session).summary
    assert summary.label_state == "rename"
    assert not summary.speaker_pass_failed
    assert rig.store.read(session).lines[1].label == "Bea"


def test_an_older_file_session_without_the_key_has_no_mark(rig):
    session = file_session(rig, ("speaker-1", "speaker-2"))

    metadata = json.loads((rig.root / "sessions" / session / "session.json").read_text())
    assert "speaker_pass_failed" not in metadata
    assert not rig.store.read(session).summary.speaker_pass_failed


def _record_the_model(monkeypatch):
    models = []

    def record(samples, model, **options):
        models.append(model)
        return level_pieces(samples, model, **options)

    monkeypatch.setattr(voice_split, "find_speech_pieces", record)
    return models


def test_rediarize_gives_the_pass_the_downloaded_speaker_model(rig, monkeypatch):
    models = _record_the_model(monkeypatch)

    rig.jobs.rediarize(recorded(rig.root))

    assert models == [rig.root / "models" / "live" / "nemo_en_titanet_small.onnx"]


def test_an_older_session_without_metadata_still_splits(rig):
    session = recorded(rig.root)
    (rig.root / "sessions" / session / "session.json").unlink()

    rig.jobs.rediarize(session)

    assert len(rig.store.read(session).lines) == 4


def test_rediarize_stops_the_worker_it_started(rig):
    session = recorded(rig.root)
    made = []

    class Spy(Worker):
        def __init__(self, config, *, transport):
            super().__init__(config, transport=transport)
            made.append(self)

    rig.jobs._worker_factory = Spy
    rig.jobs.rediarize(session)

    assert [worker.closed for worker in made] == [True]
    assert made[0].calls == 2
