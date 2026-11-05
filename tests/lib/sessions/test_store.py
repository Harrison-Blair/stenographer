# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionNotFoundError, SessionStore, export_transcript


def _line(start: float, end: float, speaker_id: str, label: str, text: str) -> TranscriptLine:
    return TranscriptLine(
        start=start,
        end=end,
        wall="2026-03-02T04:05:07+00:00",
        source="system" if speaker_id != "you" else "mic",
        speaker_id=speaker_id,
        label=label,
        text=text,
    )


def _write_session(data_root, started_at, *, finish=True):
    writer = SessionWriter.open(data_root, started_at)
    writer.write_audio("mic", np.full(16000, 0.25, dtype=np.float32))
    writer.write_audio("system", np.zeros(32000, dtype=np.float32))
    writer.append_line(_line(0.0, 0.5, "speaker-1", "Speaker 1", "first placeholder"))
    writer.append_line(_line(1.0, 2.0, "speaker-1", "Speaker 1", "second placeholder"))
    writer.append_line(_line(0.5, 1.0, "you", "You", "third placeholder"))
    writer.relabel({"speaker-1": "Alice"})
    if finish:
        writer.close()
    return writer.path


def test_list_and_read_sessions_returns_metrics_renames_and_activity(tmp_path):
    started = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
    older = _write_session(tmp_path, started)
    newer = _write_session(tmp_path, started + timedelta(minutes=1))
    store = SessionStore(tmp_path / "sessions")

    sessions = store.list_sessions()

    assert [session.session_id for session in sessions] == [newer.name, older.name]
    summary = sessions[0]
    assert summary.started_at == started + timedelta(minutes=1)
    assert summary.duration_seconds == 2.0
    assert summary.speaker_count == 2
    assert summary.audio_size_bytes == sum(
        (newer / name).stat().st_size for name in ("mic.flac", "system.flac")
    )
    assert not summary.interrupted

    detail = store.read(newer.name)

    assert [line.label for line in detail.lines] == ["Alice", "You", "Alice"]
    assert detail.talk_time == {"Alice": 1.5, "You": 0.5}
    assert set(detail.activity) == {"mic", "system"}
    assert detail.activity["mic"]
    assert max(detail.activity["mic"]) > 0
    assert max(detail.activity["system"]) == 0


def test_revisions_preserve_originals_and_rename_current_lines(tmp_path):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    original_jsonl = (session / "transcript.jsonl").read_bytes()
    original_markdown = (session / "transcript.md").read_bytes()
    store = SessionStore(tmp_path / "sessions")
    lines = store.read(session.name).lines
    revised_lines = tuple(
        replace(line, text="revised placeholder") if line.speaker_id == "speaker-1" else line
        for line in lines
    )

    revision = store.write_revision(
        session.name, revised_lines, method="re-transcribe", expected_revision="transcript.jsonl"
    )

    assert revision == "transcript.r2.jsonl"
    assert (session / "transcript.jsonl").read_bytes() == original_jsonl
    assert (session / "transcript.md").read_bytes() == original_markdown
    assert json.loads((session / "session.json").read_text(encoding="utf-8")) == {
        "current_revision": "transcript.r2.jsonl",
        "kind": "rec",
        "method": "re-transcribe",
    }
    assert "revised placeholder" in (session / "transcript.r2.md").read_text(encoding="utf-8")
    assert store.read(session.name).revision == revision

    renamed_revision = store.rename_speaker(session.name, "speaker-1", "Bob")
    detail = store.read(session.name)

    assert renamed_revision == "transcript.r3.jsonl"
    assert [line.label for line in detail.lines] == ["Bob", "You", "Bob"]
    assert detail.revision == renamed_revision
    assert (session / "transcript.jsonl").read_bytes() == original_jsonl
    assert (session / "transcript.r2.jsonl").read_text(encoding="utf-8").count("Alice") == 2

    for _ in range(7):
        revision = store.write_revision(
            session.name,
            detail.lines,
            method="relabel",
            expected_revision=store.read(session.name).revision,
        )
    assert revision == "transcript.r10.jsonl"
    assert store.read(session.name).revision == revision


def test_export_and_rename_do_not_decode_recorded_audio(tmp_path, monkeypatch):
    from stenographer.lib.sessions import reader

    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    store = SessionStore(session.parent)

    def no_decode(_path):
        raise AssertionError("audio was decoded")

    monkeypatch.setattr(reader, "_activity", no_decode)

    exported = store.export(session.name, tmp_path / "exports", "md")
    revision = store.rename_speaker(session.name, "speaker-1", "Bob")

    assert "**Alice:**" in exported.read_text(encoding="utf-8")
    assert revision == "transcript.r2.jsonl"


def test_session_and_shared_exporters_write_all_formats_privately(tmp_path):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    store = SessionStore(tmp_path / "sessions")
    output = tmp_path / "exports"

    formats = ("md", "jsonl", "srt", "txt")
    exported = {format: store.export(session.name, output, format) for format in formats}

    assert set(exported) == {"md", "jsonl", "srt", "txt"}
    assert all(path.parent == output and path.exists() for path in exported.values())
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in exported.values())
    assert "**Alice:**" in exported["md"].read_text(encoding="utf-8")
    json_lines = [
        json.loads(row) for row in exported["jsonl"].read_text(encoding="utf-8").splitlines()
    ]
    assert [row["label"] for row in json_lines] == ["Alice", "You", "Alice"]
    assert "00:00:00,000 --> 00:00:00,500" in exported["srt"].read_text(encoding="utf-8")
    assert "[00:00:00] Alice:" in exported["txt"].read_text(encoding="utf-8")

    direct = export_transcript(
        [
            TranscriptLine(
                start=0.0,
                end=0.5,
                wall="2026-03-02T04:05:07+00:00",
                source="mic",
                speaker_id="you",
                label="You",
                text="file placeholder",
            )
        ],
        output,
        "txt",
        filename="file-result",
    )
    assert direct.name == "file-result.txt"
    assert "You: file placeholder" in direct.read_text(encoding="utf-8")


def test_delete_requires_session_id_and_does_not_follow_external_links(tmp_path):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    (session / "outside-link").symlink_to(outside, target_is_directory=True)
    store = SessionStore(tmp_path / "sessions")

    store.delete(session.name)

    assert not session.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    try:
        store.delete("../outside")
    except SessionNotFoundError:
        pass
    else:
        raise AssertionError("a path outside the sessions root was accepted")
    assert sentinel.exists()


def test_revision_and_export_paths_keep_private_permissions(tmp_path):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    store = SessionStore(tmp_path / "sessions")

    revision = store.write_revision(
        session.name,
        store.read(session.name).lines,
        method="relabel",
        expected_revision="transcript.jsonl",
    )
    exported = store.export(session.name, tmp_path / "new-export-folder", "txt")

    assert session.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "sessions").stat().st_mode & 0o777 == 0o700
    assert (session / revision).stat().st_mode & 0o777 == 0o600
    assert (session / revision.replace(".jsonl", ".md")).stat().st_mode & 0o777 == 0o600
    assert (session / "session.json").stat().st_mode & 0o777 == 0o600
    assert exported.parent.stat().st_mode & 0o777 == 0o700
    assert exported.stat().st_mode & 0o777 == 0o600


def test_partial_session_is_listed_and_read_without_crashing(tmp_path):
    session = tmp_path / "sessions" / "20260302T040506Z"
    session.mkdir(parents=True)
    transcript = session / "transcript.jsonl"
    transcript.write_bytes(
        (
            json.dumps(
                {
                    "start": 0.0,
                    "end": 0.5,
                    "wall": "2026-03-02T04:05:07+00:00",
                    "source": "mic",
                    "speaker_id": "you",
                    "label": "You",
                    "text": "placeholder",
                }
            )
            + "\n{truncated\n"
        ).encode("utf-8")
        + b"\xff"
    )
    (session / "mic.flac").write_bytes(b"partial audio")
    store = SessionStore(tmp_path / "sessions")

    sessions = store.list_sessions()
    detail = store.read(session.name)

    assert len(sessions) == 1
    assert sessions[0].interrupted
    assert detail.summary.interrupted
    assert len(detail.lines) == 1
    assert detail.activity["mic"] == ()


def test_mic_diarization_flag_survives_revisions_and_old_sessions_read_false(tmp_path):
    started = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
    old = _write_session(tmp_path, started)
    writer = SessionWriter.open(tmp_path, started + timedelta(minutes=1))
    writer.mark_mic_diarized()
    writer.write_audio("mic", np.full(16000, 0.25, dtype=np.float32))
    writer.append_line(_line(0.0, 0.5, "you", "Room 1", "first placeholder"))
    writer.close()
    store = SessionStore(tmp_path / "sessions")

    assert store.read(old.name).diarize_mic is False
    marked = store.read(writer.path.name)
    assert marked.diarize_mic is True
    assert not marked.summary.interrupted
    assert (writer.path / "session.json").stat().st_mode & 0o777 == 0o600

    store.rename_speaker(writer.path.name, "you", "Dana")

    renamed = store.read(writer.path.name)
    assert renamed.revision == "transcript.r2.jsonl"
    assert renamed.diarize_mic is True
    assert store.read(old.name).diarize_mic is False


@pytest.mark.parametrize("content", [b"{truncated", b"[]", b"\xff"])
def test_revision_refuses_to_replace_invalid_metadata(tmp_path, content):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    metadata = session / "session.json"
    metadata.write_bytes(content)
    store = SessionStore(tmp_path / "sessions")

    with pytest.raises((ValueError, UnicodeError)):
        store.rename_speaker(session.name, "speaker-1", "Bob")

    assert metadata.read_bytes() == content
    assert not (session / "transcript.r2.jsonl").exists()
    assert not (session / "transcript.r2.md").exists()


def test_revision_allows_absent_legacy_metadata(tmp_path):
    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    (session / "session.json").unlink()
    store = SessionStore(tmp_path / "sessions")

    assert store.rename_speaker(session.name, "speaker-1", "Bob") == "transcript.r2.jsonl"
    assert store.read(session.name).lines[0].label == "Bob"


def test_list_sessions_reuses_a_summary_until_a_process_changes_the_session(tmp_path):
    started = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
    path = _write_session(tmp_path, started)
    store = SessionStore(tmp_path / "sessions")
    other_process = SessionStore(tmp_path / "sessions")

    (first,) = store.list_sessions()
    assert store.list_sessions()[0] is first
    assert first.speaker_count == 2 and first.duration_seconds == 2.0

    with (path / "transcript.jsonl").open("a", encoding="utf-8") as transcript:
        record = asdict(_line(2.0, 9.0, "speaker-2", "Speaker 2", "added"))
        transcript.write(json.dumps(record) + "\n")
    (appended,) = store.list_sessions()
    assert appended.speaker_count == 3 and appended.duration_seconds == 9.0

    detail = other_process.read(path.name)
    other_process.write_revision(
        path.name, detail.lines, method="diarization", expected_revision=detail.revision
    )
    (revised,) = store.list_sessions()
    assert revised.label_state == "relabeled"

    (path / "system.flac").unlink()
    (damaged,) = store.list_sessions()
    assert damaged.audio_size_bytes == (path / "mic.flac").stat().st_size

    newer = _write_session(tmp_path, started + timedelta(minutes=1))
    assert [s.session_id for s in store.list_sessions()] == [newer.name, path.name]
    other_process.delete(newer.name)
    assert [s.session_id for s in store.list_sessions()] == [path.name]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_list_sessions_sees_a_permission_change_on_a_session_file(tmp_path):
    path = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    store = SessionStore(tmp_path / "sessions")
    assert not store.list_sessions()[0].interrupted

    transcript = path / "transcript.jsonl"
    transcript.chmod(0o000)
    try:
        assert store.list_sessions()[0].interrupted
    finally:
        transcript.chmod(0o644)
    assert not store.list_sessions()[0].interrupted


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_list_sessions_keeps_other_sessions_when_a_folder_cannot_be_searched(tmp_path):
    started = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
    blocked = _write_session(tmp_path, started)
    other = _write_session(tmp_path, started + timedelta(minutes=1))
    store = SessionStore(tmp_path / "sessions")
    store.list_sessions()

    blocked.chmod(0o600)
    try:
        summaries = {summary.session_id: summary for summary in store.list_sessions()}
    finally:
        blocked.chmod(0o755)
    assert summaries[blocked.name].interrupted
    assert not summaries[other.name].interrupted


def _shared_name_session(tmp_path):
    started = datetime(2026, 11, 1, tzinfo=UTC)
    writer = SessionWriter.open(tmp_path, started)
    for index, (speaker_id, label) in enumerate(
        (("room-1", "Dana"), ("room-2", "Dana"), ("room-3", "Eve"))
    ):
        writer.append_line(_line(float(index), index + 1.0, speaker_id, label, "alpha bravo"))
    writer.close()
    return SessionStore(tmp_path / "sessions"), writer.path


def test_rename_label_changes_each_speaker_with_that_name_in_one_revision(tmp_path):
    store, path = _shared_name_session(tmp_path)
    before = len(list(path.glob("transcript*.jsonl")))

    store.rename_label(path.name, "room-2", " Diana ")

    labels = {line.speaker_id: line.label for line in store.read(path.name).lines}
    assert labels == {"room-1": "Diana", "room-2": "Diana", "room-3": "Eve"}
    assert len(list(path.glob("transcript*.jsonl"))) == before + 1


@pytest.mark.parametrize(
    ("speaker_id", "name", "message"),
    [("room-1", "  ", "must not be empty"), ("room-9", "Diana", "speaker not found")],
)
def test_rename_label_refuses_without_a_new_revision(tmp_path, speaker_id, name, message):
    store, path = _shared_name_session(tmp_path)
    revision = store.read(path.name).revision

    with pytest.raises(ValueError, match=message):
        store.rename_label(path.name, speaker_id, name)

    assert store.read(path.name).revision == revision


def test_rename_label_does_not_decode_recorded_audio(tmp_path, monkeypatch):
    from stenographer.lib.sessions import reader

    session = _write_session(tmp_path, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    store = SessionStore(session.parent)

    def no_decode(_path):
        raise AssertionError("audio was decoded")

    monkeypatch.setattr(reader, "_activity", no_decode)

    assert store.rename_label(session.name, "speaker-1", "Bob") == "transcript.r2.jsonl"
