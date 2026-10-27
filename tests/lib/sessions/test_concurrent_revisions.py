# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-session serialization and atomic revision writes across store instances."""

from __future__ import annotations

import os
import threading
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionWriteCancelledError, StaleRevisionError


def _session(data_root):
    writer = SessionWriter.open(data_root, datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC))
    writer.write_audio("system", np.zeros(16000, dtype=np.float32))
    writer.append_line(TranscriptLine(0.0, 0.5, "", "system", "speaker-1", "Speaker 1", "alpha"))
    writer.append_line(TranscriptLine(0.5, 1.0, "", "system", "speaker-2", "Speaker 2", "bravo"))
    writer.close()
    return writer.path


def _snapshot(directory):
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _labels(store, session_id):
    return [(line.speaker_id, line.label) for line in store.read(session_id).lines]


def test_concurrent_writes_from_one_read_keep_the_first_and_reject_the_stale_one(tmp_path):
    session = _session(tmp_path)
    first_store = SessionStore(tmp_path / "sessions")
    second_store = SessionStore(tmp_path / "sessions")
    barrier = threading.Barrier(2)
    results = {}

    def write(name, store, text):
        detail = store.read(session.name)
        barrier.wait(timeout=5)
        lines = [replace(line, text=text) for line in detail.lines]
        if name == "second":
            first_done.wait(timeout=5)
        try:
            results[name] = store.write_revision(
                session.name, lines, method="re-transcribe", expected_revision=detail.revision
            )
        except StaleRevisionError as exc:
            results[name] = exc
        if name == "first":
            first_done.set()

    first_done = threading.Event()
    threads = [
        threading.Thread(target=write, args=("first", first_store, "charlie")),
        threading.Thread(target=write, args=("second", second_store, "delta")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert results["first"] == "transcript.r2.jsonl"
    assert isinstance(results["second"], StaleRevisionError)
    detail = first_store.read(session.name)
    assert detail.revision == "transcript.r2.jsonl"
    assert [line.text for line in detail.lines] == ["charlie", "charlie"]
    assert not (session / "transcript.r3.jsonl").exists()


def test_concurrent_rename_between_read_and_write_is_kept(tmp_path):
    session = _session(tmp_path)
    writer_store = SessionStore(tmp_path / "sessions")
    rename_store = SessionStore(tmp_path / "sessions")
    detail = writer_store.read(session.name)

    renamer = threading.Thread(
        target=rename_store.rename_speaker, args=(session.name, "speaker-1", "Alice")
    )
    renamer.start()
    renamer.join(timeout=5)
    with pytest.raises(StaleRevisionError, match="changed"):
        writer_store.write_revision(
            session.name,
            [replace(line, text="charlie") for line in detail.lines],
            method="re-transcribe",
            expected_revision=detail.revision,
        )

    assert _labels(writer_store, session.name) == [
        ("speaker-1", "Alice"),
        ("speaker-2", "Speaker 2"),
    ]
    assert [line.text for line in writer_store.read(session.name).lines] == ["alpha", "bravo"]


@pytest.mark.parametrize("operation", ("delete", "rename"))
def test_concurrent_delete_and_rename_wait_for_a_running_write(tmp_path, operation):
    session = _session(tmp_path)
    writer_store = SessionStore(tmp_path / "sessions")
    other_store = SessionStore(tmp_path / "sessions")
    detail = writer_store.read(session.name)
    inside_write = threading.Event()
    release = threading.Event()

    def hold_lock():
        inside_write.set()
        assert release.wait(timeout=5)
        return False

    writer = threading.Thread(
        target=writer_store.write_revision,
        args=(session.name, detail.lines),
        kwargs={
            "method": "re-transcribe",
            "expected_revision": detail.revision,
            "should_cancel": hold_lock,
        },
    )
    writer.start()
    assert inside_write.wait(timeout=5)
    errors = []

    def run_other():
        try:
            if operation == "delete":
                other_store.delete(session.name)
            else:
                other_store.rename_speaker(session.name, "speaker-1", "Alice")
        except Exception as exc:
            errors.append(exc)

    other = threading.Thread(target=run_other)
    other.start()
    other.join(timeout=0.3)
    assert other.is_alive()
    assert session.exists()
    release.set()
    writer.join(timeout=5)
    other.join(timeout=5)

    assert errors == []
    if operation == "delete":
        assert not session.exists()
    else:
        assert writer_store.read(session.name).revision == "transcript.r3.jsonl"
        assert _labels(writer_store, session.name)[0] == ("speaker-1", "Alice")


@pytest.mark.parametrize(
    "target", ("transcript.r2.jsonl", "transcript.r2.md", "session.json", "write")
)
def test_concurrent_safe_injected_failure_leaves_the_session_byte_identical(
    tmp_path, monkeypatch, target
):
    session = _session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    detail = store.read(session.name)
    before = _snapshot(session)
    original_replace = os.replace
    original_fsync = os.fsync

    def failing_replace(source, destination, *args, **kwargs):
        if os.path.basename(destination) == target:
            raise OSError("injected replace failure")
        return original_replace(source, destination, *args, **kwargs)

    calls = []

    def failing_fsync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("injected write failure")
        return original_fsync(fd)

    if target == "write":
        monkeypatch.setattr(os, "fsync", failing_fsync)
    else:
        monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="injected"):
        store.write_revision(
            session.name,
            [replace(line, text="charlie") for line in detail.lines],
            method="re-transcribe",
            expected_revision=detail.revision,
        )
    monkeypatch.undo()

    assert _snapshot(session) == before
    assert store.read(session.name).revision == "transcript.jsonl"


@pytest.mark.parametrize("cancel_at", (1, 2, 3, 4))
def test_concurrent_safe_cancel_at_each_step_leaves_the_session_byte_identical(
    tmp_path, cancel_at
):
    session = _session(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    detail = store.read(session.name)
    before = _snapshot(session)
    checks = []

    def should_cancel():
        checks.append(True)
        return len(checks) >= cancel_at

    with pytest.raises(SessionWriteCancelledError):
        store.write_revision(
            session.name,
            [replace(line, text="charlie") for line in detail.lines],
            method="re-transcribe",
            expected_revision=detail.revision,
            should_cancel=should_cancel,
        )

    assert _snapshot(session) == before
