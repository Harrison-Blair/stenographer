# SPDX-License-Identifier: GPL-3.0-or-later
"""Search session titles and current transcript text."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from tests.lib.sessions.helpers import make_recording

_STARTED = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)


def _recording(data_root, started_at, *texts):
    lines = (
        TranscriptLine(index, index + 0.5, "", "system", "speaker-1", "Speaker 1", text)
        for index, text in enumerate(texts)
    )
    return make_recording(data_root, lines, started_at).name


def _file_session(store, tmp_path, started_at, name, *texts):
    source = tmp_path / name
    source.write_bytes(b"RIFFdata")
    lines = [
        TranscriptLine(i, i + 0.5, "", "file", "s1", "Speaker 1", t) for i, t in enumerate(texts)
    ]
    return store.create_file_session(
        source, started_at=started_at, duration_seconds=1.0, lines=lines
    )


def test_search_matches_titles_and_transcript_text_case_insensitively_newest_first(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    older = _recording(tmp_path, _STARTED, "alpha bravo", "charlie delta")
    newer = _recording(tmp_path, _STARTED + timedelta(days=1), "echo Foxtrot")
    newest = _file_session(
        store, tmp_path, _STARTED + timedelta(days=2), "Golf Hotel.wav", "india juliet"
    )
    everyone = [newest, newer, older]

    assert [s.session_id for s in store.list_sessions()] == everyone
    assert store.search("CHARLIE") == (older,)
    assert store.search("foxtrot") == (newer,)
    assert store.search("o") == tuple(everyone)
    assert store.search("golf hotel") == (newest,)
    assert store.search("india") == (newest,)
    assert store.search(older.lower()) == (older,)
    assert store.search("2026-03-03 04:05") == (newer,)
    assert store.search("2026-03-02") == (older,)
    assert store.search("kilo") == ()
    assert store.search("") == tuple(everyone)
    assert store.search("   ") == tuple(everyone)


def test_search_matches_recording_displayed_local_time(tmp_path, monkeypatch):
    with monkeypatch.context() as env:
        env.setenv("TZ", "UTC+5")
        time.tzset()
        try:
            store = SessionStore(tmp_path / "sessions")
            session = _recording(tmp_path, _STARTED, "hello")
            assert store.search("01 Mar 23:05") == (session,)
            assert store.search("2026-03-02 04:05") == (session,)
        finally:
            env.undo()
            time.tzset()


def test_search_reads_only_the_current_revision(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = _recording(tmp_path, _STARTED, "alpha bravo", "charlie delta")
    assert store.search("bravo") == (session,)
    detail = store.read(session)

    revised = tuple(
        replace(line, text="alpha") if "bravo" in line.text else line for line in detail.lines
    )
    store.write_revision(session, revised, method="edit", expected_revision=detail.revision)

    assert store.search("bravo") == ()
    assert store.search("charlie") == (session,)


def test_search_sees_a_rewritten_revision_file(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = _recording(tmp_path, _STARTED, "alpha bravo")
    assert store.search("bravo") == (session,)
    transcript = tmp_path / "sessions" / session / "transcript.jsonl"
    stat = transcript.stat()
    transcript.write_text(transcript.read_text().replace("bravo", "zulu"))
    os.utime(transcript, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert store.search("bravo") == ()
    assert store.search("zulu") == (session,)


def test_search_drops_a_deleted_session(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    kept = _recording(tmp_path, _STARTED, "alpha bravo")
    gone = _recording(tmp_path, _STARTED + timedelta(hours=1), "alpha charlie")
    assert store.search("alpha") == (gone, kept)

    store.delete(gone)

    assert store.search("alpha") == (kept,)
    assert store.search("charlie") == ()
    assert store.search("") == (kept,)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files without permission")
@pytest.mark.parametrize("path_kind", ("folder", "transcript"))
def test_search_skips_unreadable_sessions_and_rereads_them_after_restore(tmp_path, path_kind):
    store = SessionStore(tmp_path / "sessions")
    readable = _recording(tmp_path, _STARTED, "alpha bravo")
    locked = _recording(tmp_path, _STARTED + timedelta(hours=1), "alpha charlie")
    folder = tmp_path / "sessions" / locked
    path = folder if path_kind == "folder" else folder / "transcript.jsonl"
    mode = 0o700 if path_kind == "folder" else 0o600
    path.chmod(0)
    try:
        assert store.search("alpha") == (readable,)
        assert store.search("charlie") == ()
        assert store.search(locked) == ()
        assert store.search("2026-03-02 05:05") == ()
    finally:
        path.chmod(mode)

    assert store.search("charlie") == (locked,)


def test_search_writes_no_file_and_logs_no_query_or_line_text(tmp_path, caplog):
    store = SessionStore(tmp_path / "sessions")
    session = _recording(tmp_path, _STARTED, "alpha secretword")
    before = sorted((path, path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))

    with caplog.at_level(logging.DEBUG):
        assert store.search("SecretWord") == (session,)
        assert store.search("missingquery") == ()

    assert sorted((path, path.stat().st_mtime_ns) for path in tmp_path.rglob("*")) == before
    logged = caplog.text.lower()
    assert "secretword" not in logged
    assert "missingquery" not in logged
