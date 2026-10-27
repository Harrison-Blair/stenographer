# SPDX-License-Identifier: GPL-3.0-or-later
"""Session kinds, label states, and file-session source rules."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionSourceError

_STARTED = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)


def _line(start, end, source, speaker_id, label, text="alpha bravo"):
    return TranscriptLine(start, end, "", source, speaker_id, label, text)


def _recording(data_root, started_at=_STARTED):
    writer = SessionWriter.open(data_root, started_at)
    writer.write_audio("system", np.zeros(16000, dtype=np.float32))
    writer.append_line(_line(0.0, 0.5, "system", "speaker-1", "Speaker 1"))
    writer.close()
    return writer.path


def _file_session(sessions_root, *, metadata=None, transcript=True, source=b"RIFFdata"):
    directory = sessions_root / "20260302T040506Z"
    directory.mkdir(parents=True, mode=0o700)
    (directory / "source.wav").write_bytes(source)
    if transcript:
        row = json.dumps(
            {
                "start": 0.0,
                "end": 1.0,
                "wall": "",
                "source": "file",
                "speaker_id": "speaker-1",
                "label": "Speaker 1",
                "text": "alpha bravo",
            }
        )
        (directory / "transcript.jsonl").write_text(row + "\n", encoding="utf-8")
        (directory / "transcript.md").write_text("# Transcript\n", encoding="utf-8")
    values = {
        "current_revision": "transcript.jsonl",
        "duration_seconds": 42.5,
        "kind": "file",
        "source_file": "source.wav",
        "source_name": "Standup Notes.wav",
    }
    values.update(metadata or {})
    (directory / "session.json").write_text(json.dumps(values), encoding="utf-8")
    return directory


def test_old_session_folder_without_kind_or_session_json_reads_as_live_recording(tmp_path):
    # A folder as written by versions before session kinds existed.
    directory = tmp_path / "sessions" / "20250101T000000Z"
    directory.mkdir(parents=True)
    sf.write(directory / "mic.flac", np.zeros(16000, dtype=np.float32), 16000)
    (directory / "transcript.jsonl").write_text(
        json.dumps(
            {
                "start": 0.0,
                "end": 0.5,
                "wall": "2025-01-01T00:00:00+00:00",
                "source": "mic",
                "speaker_id": "you",
                "label": "You",
                "text": "alpha bravo",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "transcript.md").write_text("# Session transcript\n", encoding="utf-8")
    store = SessionStore(tmp_path / "sessions")

    (summary,) = store.list_sessions()

    assert summary.kind == "rec"
    assert summary.source_name is None
    assert summary.label_state == "live"
    assert not summary.interrupted
    assert summary.duration_seconds == 1.0
    assert not (directory / "session.json").exists()


def test_new_recording_writes_rec_kind(tmp_path):
    session = _recording(tmp_path)

    metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))

    assert metadata["kind"] == "rec"
    assert SessionStore(tmp_path / "sessions").read(session.name).summary.kind == "rec"


def test_label_state_follows_the_current_revision_method(tmp_path):
    session = _recording(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    assert store.list_sessions()[0].label_state == "live"

    lines = store.read(session.name).lines
    store.write_revision(
        session.name, lines, method="diarization", expected_revision="transcript.jsonl"
    )
    assert store.list_sessions()[0].label_state == "relabeled"

    store.rename_speaker(session.name, "speaker-1", "Alice")
    assert store.list_sessions()[0].label_state == "rename"

    store.write_revision(
        session.name,
        store.read(session.name).lines,
        method="re-transcribe",
        expected_revision="transcript.r3.jsonl",
    )
    assert store.list_sessions()[0].label_state == "re-transcribe"


def test_file_session_summary_uses_probe_duration_and_source_size(tmp_path):
    directory = _file_session(tmp_path / "sessions", source=b"x" * 1234)
    store = SessionStore(tmp_path / "sessions")

    (summary,) = store.list_sessions()

    assert summary.kind == "file"
    assert summary.source_name == "Standup Notes.wav"
    assert summary.duration_seconds == 42.5
    assert summary.audio_size_bytes == 1234
    assert summary.speaker_count == 1
    assert not summary.interrupted
    assert store.source_audio(summary.session_id) == directory / "source.wav"


@pytest.mark.parametrize("damage", ("missing", "malformed"))
def test_file_session_with_a_broken_transcript_reads_as_interrupted(tmp_path, damage):
    directory = _file_session(tmp_path / "sessions")
    if damage == "missing":
        (directory / "transcript.jsonl").unlink()
    else:
        (directory / "transcript.jsonl").write_text("{not json\n", encoding="utf-8")

    (summary,) = SessionStore(tmp_path / "sessions").list_sessions()

    assert summary.kind == "file"
    assert summary.interrupted


@pytest.mark.parametrize(
    "source_file",
    ("/etc/hostname", "../outside.wav", "source.link", "source.toolongext", "notes.wav", 7),
)
def test_invalid_source_file_reads_as_interrupted_and_no_outside_file_is_read(
    tmp_path, monkeypatch, source_file
):
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"y" * 999)
    directory = _file_session(tmp_path / "sessions", metadata={"source_file": source_file})
    (directory / "source.link").symlink_to(outside)
    (directory / "notes.wav").write_bytes(b"z" * 10)
    store = SessionStore(tmp_path / "sessions")
    touched = []
    original_lstat = os.lstat
    original_stat = os.stat

    def record_lstat(path, *args, **kwargs):
        touched.append(os.fspath(path))
        return original_lstat(path, *args, **kwargs)

    def record_stat(path, *args, **kwargs):
        touched.append(os.fspath(path))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", record_lstat)
    monkeypatch.setattr(os, "stat", record_stat)

    (summary,) = store.list_sessions()
    monkeypatch.undo()

    assert summary.interrupted
    assert summary.audio_size_bytes == 0
    assert str(outside) not in touched
    assert "/etc/hostname" not in touched
    with pytest.raises(SessionSourceError, match="source audio"):
        store.source_audio(summary.session_id)


def test_source_audio_refuses_a_recording(tmp_path):
    session = _recording(tmp_path)

    with pytest.raises(SessionSourceError, match="not a file session"):
        SessionStore(tmp_path / "sessions").source_audio(session.name)


def test_reader_orders_equal_start_times_mic_first_then_by_end(tmp_path):
    session = _recording(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    store.write_revision(
        session.name,
        [
            _line(0.0, 1.0, "system", "system-1", "Sys"),
            _line(0.0, 3.0, "mic", "mic-2", "Long"),
            _line(0.0, 2.0, "mic", "mic-1", "Short"),
            _line(1.0, 1.5, "system", "system-2", "Next"),
        ],
        method="file-transcribe",
        expected_revision="transcript.jsonl",
    )

    lines = store.read(session.name).lines

    assert [line.speaker_id for line in lines] == ["mic-1", "mic-2", "system-1", "system-2"]
