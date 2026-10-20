# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np

from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions.store import SessionStore


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

    revision = store.write_revision(session.name, revised_lines, method="re-transcribe")

    assert revision == "transcript.r2.jsonl"
    assert (session / "transcript.jsonl").read_bytes() == original_jsonl
    assert (session / "transcript.md").read_bytes() == original_markdown
    assert json.loads((session / "session.json").read_text(encoding="utf-8")) == {
        "current_revision": "transcript.r2.jsonl",
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


def test_partial_session_is_listed_and_read_without_crashing(tmp_path):
    session = tmp_path / "sessions" / "20260302T040506Z"
    session.mkdir(parents=True)
    transcript = session / "transcript.jsonl"
    transcript.write_text(
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
        + "\n{truncated",
        encoding="utf-8",
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
