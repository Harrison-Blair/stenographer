# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for saved sessions in the hub."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import numpy as np
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore


class FakeServices:
    def __init__(self, sessions_root):
        self.session_store = SessionStore(sessions_root)
        self.recording = False
        self.files_running = False
        self.active_session_id = None
        self.actions = []
        self.playing = False
        self.job_started = threading.Event()
        self.release_job = threading.Event()

    def toggle_session_playback(self, session_id):
        self.playing = not self.playing
        self.actions.append(("play", session_id, self.playing))

    def rediarize_session(self, session_id):
        self._run_fake_job(session_id, "diarization")

    def retranscribe_session(self, session_id):
        self._run_fake_job(session_id, "re-transcribe")

    def _run_fake_job(self, session_id, method):
        self.actions.append((method, session_id))
        self.job_started.set()
        if not self.release_job.wait(timeout=2):
            raise TimeoutError("test job timed out")
        detail = self.session_store.read(session_id)
        self.session_store.write_revision(session_id, detail.lines, method=method)


def _write_session(root, started_at, *, interrupted=False):
    writer = SessionWriter.open(root.parent, started_at)
    audio = np.full(48_000, 0.1, dtype=np.float32)
    writer.write_audio("mic", audio)
    writer.write_audio("system", audio)
    writer.append_line(
        TranscriptLine(0.0, 1.2, "", "system", "speaker-1", "Speaker 1", "first fixture line")
    )
    writer.append_line(TranscriptLine(1.2, 2.4, "", "mic", "you", "You", "second fixture line"))
    writer.close()
    if interrupted:
        (writer.path / "system.flac").unlink()
    return writer.path


def test_sessions_list_and_detail_show_storage_activity_and_transcript(tmp_path):
    sessions_root = tmp_path / "sessions"
    latest = _write_session(
        sessions_root,
        datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
    )
    older = _write_session(
        sessions_root,
        datetime(2026, 10, 20, 0, 28, tzinfo=UTC),
        interrupted=True,
    )
    app = HubApp(FakeServices(sessions_root))

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            storage = str(app.query_one("#sessions-storage", Static).render())
            listing = str(app.query_one("#sessions-list", Static).render())
            detail = str(app.query_one("#sessions-detail", Static).render())
            assert "2 sessions" in storage
            assert "audio" in storage
            audio_bytes = sum(path.stat().st_size for path in sessions_root.glob("*/*.flac"))
            assert f"{audio_bytes:.1f} B" in storage
            assert "2026-10-20 01:12" in listing
            assert "2026-10-20 00:28" in listing
            assert "0:03  2 spk" in listing
            assert "! interrupted" in listing
            assert "labels: live" in detail
            assert "Speaker 1 0:01" in detail and "You 0:01" in detail
            assert "mic" in detail and "sys" in detail
            assert "first fixture line" in detail
            assert "second fixture line" in detail

            await pilot.press("down")
            await pilot.pause(0.1)
            assert app.sessions_panel.selected_session_id == older.name
            assert "sys  no audio" in str(app.query_one("#sessions-detail", Static).render())
            await pilot.press("up")
            await pilot.pause(0.1)
            assert app.sessions_panel.selected_session_id == latest.name

    asyncio.run(exercise())
    assert latest.is_dir()


def test_active_recording_is_not_listed_as_a_saved_session(tmp_path):
    sessions_root = tmp_path / "sessions"
    active = _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    services = FakeServices(sessions_root)
    services.active_session_id = active.name
    app = HubApp(services)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)
            storage = str(app.query_one("#sessions-storage", Static).render())
            listing = str(app.query_one("#sessions-list", Static).render())
            assert "0 sessions" in storage
            assert listing == "No saved sessions."

    asyncio.run(exercise())


def test_session_playback_toggles_and_jobs_run_without_blocking_navigation(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(
        sessions_root,
        datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
    )
    services = FakeServices(sessions_root)
    app = HubApp(services)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)
            await pilot.press("p", "p")
            assert services.actions[:2] == [
                ("play", session.name, True),
                ("play", session.name, False),
            ]

            await pilot.press("d")
            await pilot.pause(0.05)
            assert services.job_started.is_set()
            assert "Re-diarizing" in str(app.query_one("#sessions-detail", Static).render())
            await pilot.press("1")
            assert app.current_section == "live"
            services.release_job.set()
            await pilot.press("3")
            for _ in range(20):
                await pilot.pause(0.02)
                if app._session_job_status is None:
                    break
            assert app._session_job_status is None
            assert services.session_store.read(session.name).revision == "transcript.r2.jsonl"

            services.job_started.clear()
            services.release_job.clear()
            await pilot.press("t")
            await pilot.pause(0.05)
            assert services.job_started.is_set()
            services.release_job.set()
            for _ in range(20):
                await pilot.pause(0.02)
                if app._session_job_status is None:
                    break
            assert app._session_job_status is None
            detail = services.session_store.read(session.name)
            assert detail.revision == "transcript.r3.jsonl"
            assert services.actions[-2:] == [
                ("diarization", session.name),
                ("re-transcribe", session.name),
            ]

    try:
        asyncio.run(exercise())
    finally:
        services.release_job.set()


def test_session_rename_export_and_delete_use_confirmed_session(tmp_path):
    sessions_root = tmp_path / "sessions"
    session = _write_session(
        sessions_root,
        datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC),
    )
    services = FakeServices(sessions_root)
    app = HubApp(services)
    output = tmp_path / "exports"

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)
            await pilot.press("r")
            speaker_id = app.screen.query_one("#config-prompt-input")
            assert speaker_id.value == "speaker-1"
            await pilot.press("enter")
            await pilot.press("ctrl+a", "ctrl+k", *tuple("Alice"), "enter")
            await pilot.pause(0.1)
            renamed_detail = str(app.query_one("#sessions-detail", Static).render())
            assert "Alice" in renamed_detail
            assert "labels: re-labelled" in renamed_detail

            await pilot.press("x")
            await pilot.press("ctrl+a", "ctrl+k", *tuple(f"md {output}"), "enter")
            for _ in range(20):
                await pilot.pause(0.02)
                if (output / f"{session.name}.md").exists():
                    break
            assert (output / f"{session.name}.md").is_file()

            await pilot.press("delete")
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert session.name in prompt
            await pilot.click("#cancel-quit")
            assert session.is_dir()

            await pilot.press("delete")
            await pilot.click("#confirm-quit")
            await pilot.pause(0.1)
            assert not session.exists()

    asyncio.run(exercise())
