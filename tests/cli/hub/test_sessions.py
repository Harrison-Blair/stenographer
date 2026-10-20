# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for saved sessions in the hub."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import numpy as np
from rich.color import Color
from textual.widgets import Rule, Static

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

            storage = app.query_one("#sidebar-card", Static).render().plain
            listing = app.query_one("#sessions-list", Static).render().plain
            detail = app.query_one("#sessions-detail", Static).render()
            transcript = app.query_one("#sessions-transcript", Static).render()
            assert "storage" in storage
            assert "2 sessions" in storage
            assert "audio" in storage
            audio_bytes = sum(path.stat().st_size for path in sessions_root.glob("*/*.flac"))
            assert f"{audio_bytes:.1f} B" in storage
            assert "▶ 2026-10-20 01:12" in listing
            assert "2026-10-20 00:28" in listing
            assert "0:03  2 spk" in listing
            assert "! interrupted" in listing
            list_widget = app.query_one("#sessions-list", Static).render()
            selected_offset = list_widget.plain.index("▶")
            selected_style = next(
                span.style.rich_style
                for span in list_widget.spans
                if span.start <= selected_offset < span.end
            )
            assert selected_style.bold
            assert selected_style.color is not None
            assert selected_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
            assert selected_style.bgcolor is None or selected_style.bgcolor.is_default
            assert app.query_one("#sessions-detail-labels", Static).render().plain == "labels: live"
            assert "Speaker 1 0:01" in detail.plain and "You 0:01" in detail.plain
            assert "mic" in detail.plain and "sys" in detail.plain
            assert "first fixture line" in transcript.plain
            assert "second fixture line" in transcript.plain
            speaker_offset = transcript.plain.index("Speaker 1")
            speaker_style = next(
                span.style for span in transcript.spans if span.start <= speaker_offset < span.end
            )
            assert speaker_style.bold
            assert speaker_style.foreground.rgb == (255, 175, 95)

            await pilot.press("down")
            await pilot.pause(0.1)
            assert app.sessions_panel.selected_session_id == older.name
            assert "sys  no audio" in str(app.query_one("#sessions-detail", Static).render())
            await pilot.press("up")
            await pilot.pause(0.1)
            assert app.sessions_panel.selected_session_id == latest.name

    asyncio.run(exercise())
    assert latest.is_dir()


def test_sessions_panels_render_borders_and_board_proportions(tmp_path):
    app = HubApp(FakeServices(tmp_path / "sessions"))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            listing = app.query_one("#sessions-list-scroll")
            detail = app.query_one("#sessions-detail-scroll")
            assert listing.styles.border.top[0] == "round"
            assert detail.styles.border.top[0] == "round"
            assert listing.region.x < detail.region.x
            assert listing.region.width < detail.region.width
            assert listing.region.y == detail.region.y
            assert listing.region.height == detail.region.height
            assert "storage" in app.query_one("#sidebar-card", Static).render().plain
            assert (
                app.query_one("#sidebar-card", Static).region.x
                == app.query_one("#sidebar", Static).region.x
            )
            assert (
                app.query_one("#sidebar-card", Static).region.y
                > app.query_one("#sidebar", Static).region.y
            )
            assert listing.border_title == "saved"
            assert detail.border_title == ""
            assert app.query_one("#sessions-detail-title", Static).render().plain == "session"
            assert not list(app.query("#sessions-storage"))
            hints = app.query_one("#key-hints", Static).render().plain
            for hint in (
                "p play",
                "d re-diarize",
                "t re-transcribe",
                "r rename",
                "x export",
                "del delete",
            ):
                assert hint in hints

    asyncio.run(exercise())


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
            storage = app.query_one("#sidebar-card", Static).render().plain
            listing = app.query_one("#sessions-list", Static).render().plain
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


def test_sessions_transcript_rule_fills_detail_width_on_first_layout(tmp_path):
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    app = HubApp(FakeServices(sessions_root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            detail_panel = app.query_one("#sessions-detail-scroll")
            rule = app.query_one("#sessions-detail-rule", Rule)
            assert rule.region.width == detail_panel.content_region.width - 2
            assert rule.region.width > 1

    asyncio.run(exercise())


def test_sessions_border_titles_use_default_foreground_and_bold(tmp_path):
    app = HubApp(FakeServices(tmp_path / "sessions"))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            for panel_id in ("#sessions-list-scroll", "#sessions-detail-scroll"):
                styles = app.query_one(panel_id).styles
                assert styles.border_title_color.css == "ansi_default"
                assert styles.border_title_style.bold
            title_styles = app.query_one("#sessions-detail-title", Static).styles
            assert title_styles.color.css == "ansi_default"
            assert title_styles.text_style.bold

    asyncio.run(exercise())


def test_session_label_status_is_right_aligned_on_the_title_row(tmp_path):
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    app = HubApp(FakeServices(sessions_root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            title = app.query_one("#sessions-detail-title", Static)
            labels = app.query_one("#sessions-detail-labels", Static)
            assert title.render().plain == app.sessions_panel.selected_session_id
            assert labels.render().plain == "labels: live"
            assert title.region.y == labels.region.y
            assert labels.styles.text_align == "right"

    asyncio.run(exercise())


def test_sessions_transcript_rows_render_after_rule_with_synthetic_text(tmp_path):
    sessions_root = tmp_path / "sessions"
    _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
    app = HubApp(FakeServices(sessions_root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.1)

            rule = app.query_one("#sessions-detail-rule", Rule)
            transcript = app.query_one("#sessions-transcript", Static)
            assert rule.region.y < transcript.region.y
            rendered = transcript.render()
            assert "00:00:01" in rendered.plain
            assert "Speaker 1" in rendered.plain
            assert "first fixture line" in rendered.plain
            speaker_offset = rendered.plain.index("Speaker 1")
            speaker_style = next(
                span.style for span in rendered.spans if span.start <= speaker_offset < span.end
            )
            assert speaker_style.bold
            assert speaker_style.foreground.rgb == (255, 175, 95)

    asyncio.run(exercise())


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
            renamed_detail = app.query_one("#sessions-detail", Static).render().plain
            assert "Alice" in renamed_detail
            assert app.query_one("#sessions-detail-labels", Static).render().plain == (
                "labels: re-labelled at stop"
            )

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
