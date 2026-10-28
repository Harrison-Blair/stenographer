# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Library screen with sessions in ``tmp_path`` and fake services."""

from __future__ import annotations

import asyncio
import gc
import json
import tempfile
import threading
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.sparkline import Sparkline
from stenographer.lib.config.models import Config
from stenographer.lib.files.media import DecodedAudio
from stenographer.lib.files.models import FileJobProgress
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.errors import SessionSourceError
from tests.cli.hub.test_session_jobs import FakePlatform, FakePlayer

REC_RELABELED = datetime(2026, 10, 27, 13, 3, tzinfo=UTC)
REC_LIVE = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
REC_INTERRUPTED = datetime(2026, 10, 23, 0, 22, tzinfo=UTC)
FAILED = "\u00d7 failed"
FILE_STARTED = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class FakeJob:
    """Stand in for ``FileJob``: the test sets each state."""

    def __init__(self, job_id: str, path: Path, *, state: str = "running", percent: int = 43):
        self.id = job_id
        self.options = SimpleNamespace(path=path, diarize=True, speaker_count=None, refine=False)
        self.state = state
        self.progress = FileJobProgress("transcribe", percent, None, ())
        self.session_id: str | None = None
        self.error: str | None = None
        self.cancel_requested = False

    def cancel(self) -> bool:
        if self.state not in {"queued", "running"}:
            return False
        self.cancel_requested = True
        return True


class FakeServices:
    def __init__(self, sessions_root: Path):
        self.session_store = SessionStore(sessions_root)
        self.recording = False
        self.active_session_id = None
        self.jobs: list[FakeJob] = []
        self.actions: list[tuple] = []
        self.job_started = threading.Event()
        self.release_job = threading.Event()
        self.play_error: Exception | None = None

    @property
    def files_jobs(self):
        return tuple(self.jobs)

    @property
    def files_running(self):
        return any(job.state in {"queued", "running"} for job in self.jobs)

    def submit_file(self, path, **options):
        job = FakeJob(f"file-{len(self.jobs) + 1}", Path(path), state="queued", percent=0)
        self.jobs.append(job)
        self.actions.append(("submit", Path(path).name))
        return job

    def cancel_file(self, job):
        self.actions.append(("cancel", job.id))
        return job.cancel()

    def toggle_session_playback(self, session_id):
        self.actions.append(("play", session_id))
        if self.play_error is not None:
            raise self.play_error

    def rediarize_session(self, session_id):
        self._run_fake_job(session_id, "diarization")

    def retranscribe_session(self, session_id):
        self._run_fake_job(session_id, "re-transcribe")

    def _run_fake_job(self, session_id, method):
        self.actions.append((method, session_id))
        self.job_started.set()
        if not self.release_job.wait(timeout=5):
            raise TimeoutError("test job timed out")
        detail = self.session_store.read(session_id)
        self.session_store.write_revision(
            session_id, detail.lines, method=method, expected_revision=detail.revision
        )


def _write_rec(root: Path, started_at, *, relabel=False, interrupted=False) -> Path:
    writer = SessionWriter.open(root.parent, started_at)
    audio = np.concatenate(
        (np.zeros(16_000, dtype=np.float32), np.full(32_000, 0.2, dtype=np.float32))
    )
    writer.write_audio("mic", audio)
    writer.write_audio("system", audio[::-1].copy())
    writer.append_line(
        TranscriptLine(0.0, 1.2, "", "system", "speaker-1", "Speaker 1", "alpha bravo charlie")
    )
    writer.append_line(TranscriptLine(1.2, 2.4, "", "mic", "you", "You", "delta echo foxtrot"))
    writer.close()
    if relabel:
        store = SessionStore(root)
        detail = store.read(writer.path.name)
        store.write_revision(
            writer.path.name,
            detail.lines,
            method="diarization",
            expected_revision=detail.revision,
        )
    if interrupted:
        (writer.path / "system.flac").unlink()
    return writer.path


def _write_file_session(root: Path, tmp_path: Path, name: str = "meeting-notes.wav") -> str:
    source = tmp_path / "sources" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    sf.write(source, np.full(16_000, 0.1, dtype=np.float32), 16_000)
    return SessionStore(root).create_file_session(
        source,
        started_at=FILE_STARTED,
        duration_seconds=1.0,
        lines=(TranscriptLine(0.0, 1.0, "", "file", "speaker-1", "Speaker 1", "golf hotel india"),),
    )


def _library(tmp_path: Path):
    root = tmp_path / "sessions"
    sessions = {
        "relabeled": _write_rec(root, REC_RELABELED, relabel=True).name,
        "live": _write_rec(root, REC_LIVE).name,
        "interrupted": _write_rec(root, REC_INTERRUPTED, interrupted=True).name,
        "file": _write_file_session(root, tmp_path),
    }
    return root, sessions


def _screen_text(app: HubApp) -> str:
    return "\n".join(
        "".join(segment.text for segment in strip._segments)
        for strip in app.screen._compositor.render_strips()
    )


def _rows(app: HubApp) -> list[str]:
    return app.screen.query_one("#library-list", Static).render().plain.splitlines()


def _card(app: HubApp) -> str:
    return str(app.screen.query_one("#sidebar-card", Static).render())


def _button(app: HubApp, button_id: str) -> HubButton:
    return app.screen.query_one(f"#{button_id}", HubButton)


async def _until(pilot, condition, message="condition not met") -> None:
    for _ in range(250):
        if condition():
            return
        await pilot.pause(0.02)
    raise AssertionError(message)


async def _open_library(pilot, app: HubApp, count: int, *, detail: bool = True) -> None:
    await pilot.press("2")
    await _until(pilot, lambda: len(app.library_screen.entries) == count, "list did not load")
    if detail:
        await _until(pilot, lambda: app.library_screen.detail is not None, "detail did not load")
    app.refresh_view()
    await pilot.pause()


# V1: list, search and select by ID


def test_library_list_cells_storage_card_and_badge(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    services.jobs.append(FakeJob("file-1", tmp_path / "sources" / "lecture.mp3"))
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 5, detail=False)
            rows = _rows(app)
            assert [row.split() for row in rows[1:]] == [
                ["27", "Oct", "13:03", "0:03", "rec", "2", "relabeled"],
                ["26", "Oct", "18:00", "0:03", "rec", "2", "live"],
                ["26", "Oct", "13:30", "0:01", "file", "1", "meeting-notes.wav"],
                ["23", "Oct", "00:22", "0:03", "rec", "2", "!", "interrupted"],
            ]
            job_row = rows[0].split()
            assert job_row[0] == "▶"
            assert job_row[-4:] == ["43%", "file", "—", "lecture.mp3"]
            header = app.screen.query_one("#library-columns", Static).render().plain.split()
            assert header == ["date", "dur", "kind", "spk", "labels"]

            card = _card(app)
            assert app.screen.query_one("#sidebar-context").border_title == "storage"
            assert "5 entries" in card
            assert "audio" in card
            assert str(root) in card
            assert app.screen.query_one("#sidebar", Static).render().plain.splitlines()[
                1
            ].split() == ["▶", "2", "Library", "5"]

            text = _screen_text(app)
            assert "[/] search titles and transcripts" in text
            assert "[n] + Transcribe a file…" in text
            hints = app.screen.query_one("#key-hints", Static).render().plain
            assert hints == (
                "n transcribe file · / search · p play · r rename · d re-diarize · "
                "t re-transcribe · x export · del delete · 1 2 3 screens · ? help · q quit"
            )

            # The interrupted label carries the danger tone in addition to its "!" glyph.
            listing = app.screen.query_one("#library-list", Static).render()
            offset = listing.plain.index("! interrupted")
            style = next(s.style for s in listing.spans if s.start <= offset < s.end)
            assert style.foreground.rgb == (255, 135, 95)

    asyncio.run(exercise())


def test_library_long_file_label_is_cut_with_an_ellipsis(tmp_path):
    root = tmp_path / "sessions"
    _write_file_session(root, tmp_path, name="a-very-long-source-file-name-" + "x" * 80 + ".wav")
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 1)
            row = _rows(app)[0]
            assert row.endswith("…")
            assert len(row) <= app.screen.query_one("#library-list").size.width

    asyncio.run(exercise())


def test_library_select_by_id_keeps_selection_and_moves_by_keys_and_clicks(tmp_path):
    root, sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            screen = app.library_screen
            assert screen.selected_id == sessions["relabeled"]
            assert screen.select_session(sessions["file"])
            assert screen.selected_id == sessions["file"]
            assert not screen.select_session("20990101T000000Z")
            assert screen.selected_id == sessions["file"]

            await pilot.press("down")
            assert screen.selected_id == sessions["interrupted"]
            await pilot.press("up", "up")
            assert screen.selected_id == sessions["live"]

            # A click on a row selects it.
            listing = app.screen.query_one("#library-list")
            await pilot.click(listing, offset=(5, 0))
            assert screen.selected_id == sessions["relabeled"]

            # A reload keeps the selection by ID even when a newer session comes first.
            screen.select_session(sessions["live"])
            newer = _write_rec(root, datetime(2026, 10, 28, 9, 0, tzinfo=UTC))
            screen.load_sessions()
            await _until(pilot, lambda: len(screen.entries) == 5)
            assert screen.selected_id == sessions["live"]

            # show_library with an ID selects it (Record "o").
            app.show_library(newer.name)
            await _until(pilot, lambda: screen.selected_id == newer.name)

    asyncio.run(exercise())


def test_library_search_filters_sessions_and_job_rows_and_escape_clears(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.jobs.append(FakeJob("file-1", tmp_path / "sources" / "Quarterly-Review.mp3"))
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 5, detail=False)
            screen = app.library_screen
            await pilot.press("slash")
            search = app.screen.query_one("#library-search", Input)
            assert search.display and search.has_focus

            # Transcript text, case-insensitive; letters go to the field.
            await pilot.press(*"GOLF")
            await _until(pilot, lambda: len(screen.entries) == 1)
            assert screen.entries[0].entry_id == sessions["file"]
            assert search.value == "GOLF"

            # A job row matches by its source file name only.
            search.value = "quarterly"
            await _until(pilot, lambda: [e.job for e in screen.entries] == [services.jobs[0]])

            # Text that only the transcripts hold.
            search.value = "foxtrot"
            await _until(pilot, lambda: len(screen.entries) == 3)
            assert {entry.entry_id for entry in screen.entries} == {
                sessions["relabeled"],
                sessions["live"],
                sessions["interrupted"],
            }

            await pilot.press("escape")
            await _until(pilot, lambda: len(screen.entries) == 5)
            assert not search.display
            assert search.value == ""

    asyncio.run(exercise())


def test_library_search_runs_off_the_event_loop(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    loop_threads = []
    original = services.session_store.search

    def search(query):
        loop_threads.append(threading.current_thread() is threading.main_thread())
        return original(query)

    services.session_store.search = search
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            await pilot.press("slash", *"golf")
            await _until(pilot, lambda: len(app.library_screen.entries) == 1)

    asyncio.run(exercise())
    assert loop_threads and not any(loop_threads)


def test_library_does_not_list_the_active_recording(tmp_path):
    root = tmp_path / "sessions"
    active = _write_rec(root, REC_LIVE)
    services = FakeServices(root)
    services.active_session_id = active.name
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            await _until(pilot, lambda: app.library_screen.entry_count == 0)
            assert "0 entries" in _card(app)
            assert "No saved sessions." in _screen_text(app)

    asyncio.run(exercise())


# V2: detail and actions


def test_library_detail_of_a_recording_and_of_a_file_session(tmp_path):
    root, sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            text = _screen_text(app)
            assert "27 Oct 2026 · 13:03 · 0:03 · recording" in text
            assert "relabeled" in str(
                app.screen.query_one("#library-detail-state", Static).render()
            )
            speakers = app.screen.query_one("#library-speakers", Static).render().plain
            assert "Speaker 1 0:01" in speakers and "You 0:01" in speakers
            for spark_id in ("#library-mic", "#library-sys"):
                spark = app.screen.query_one(spark_id, Sparkline)
                assert spark.display
                plain = spark.render().plain
                assert any(glyph in plain for glyph in "▂▃▄▅▆▇█")
            assert app.screen.query_one("#library-mic").render().plain.startswith("mic ")
            assert app.screen.query_one("#library-sys").render().plain.startswith("sys ")
            for label in (
                "[p] ▶ Play",
                "[r] Rename speaker…",
                "[d] Re-diarize",
                "[t] Re-transcribe",
                "[x] Export…",
                "[del] Delete…",
            ):
                assert label in text
            assert "00:00:00" in text and "alpha bravo charlie" in text
            assert "delta echo foxtrot" in text

            app.library_screen.select_session(sessions["file"])
            await _until(
                pilot,
                lambda: (
                    app.library_screen.detail is not None
                    and app.library_screen.detail.summary.kind == "file"
                ),
            )
            app.refresh_view()
            await pilot.pause()
            text = _screen_text(app)
            assert "26 Oct 2026 · 13:30 · 0:01 · file" in text
            # Live labels belong to a recording; a file session has no live pass.
            assert "live" not in str(app.screen.query_one("#library-detail-state").render())
            assert not app.screen.query_one("#library-mic").display
            assert not app.screen.query_one("#library-sys").display
            assert "golf hotel india" in text
            rediarize = _button(app, "library-rediarize")
            assert rediarize.disabled
            assert "d re-diarize: use Re-transcribe" in text
            await pilot.press("d")
            await pilot.pause()
            assert "use Re-transcribe" in "\n".join(str(n.message) for n in app._notifications)

            app.library_screen.select_session(sessions["interrupted"])
            await _until(
                pilot,
                lambda: (
                    app.library_screen.detail is not None
                    and app.library_screen.detail.summary.interrupted
                ),
            )
            app.refresh_view()
            await pilot.pause()
            assert "! interrupted" in str(
                app.screen.query_one("#library-detail-state", Static).render()
            )
            # The missing system audio shows a flat dotted row, not a level.
            assert "▂" not in app.screen.query_one("#library-sys").render().plain

    asyncio.run(exercise())


def _notices(app: HubApp) -> str:
    return "\n".join(str(notice.message) for notice in app._notifications)


@pytest.mark.parametrize("by", ["key", "click"])
def test_library_play_rediarize_and_retranscribe_by_key_and_click(tmp_path, by):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    app = HubApp(services)
    relabeled = sessions["relabeled"]

    async def run(pilot, key, button_id):
        if by == "key":
            await pilot.press(key)
        else:
            await pilot.click(f"#{button_id}")

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            await run(pilot, "p", "library-play")
            await _until(pilot, lambda: ("play", relabeled) in services.actions)

            await run(pilot, "t", "library-retranscribe")
            await _until(pilot, services.job_started.is_set)
            assert app.is_busy(relabeled)
            app.refresh_view()
            await pilot.pause()
            for button_id in (
                "library-rename",
                "library-rediarize",
                "library-retranscribe",
                "library-delete",
            ):
                button = _button(app, button_id)
                assert button.disabled, button_id
                assert "busy" in str(button.label), button_id
            assert not _button(app, "library-play").disabled
            assert not _button(app, "library-export").disabled

            # A second job on the busy session is refused and starts nothing.
            count = len(services.actions)
            await run(pilot, "d", "library-rediarize")
            await pilot.pause()
            if by == "key":
                assert "session busy" in _notices(app)
            assert len(services.actions) == count

            # Navigation stays free while the job runs.
            await pilot.press("1")
            assert app.current_mode == "record"
            services.release_job.set()
            await pilot.press("2")
            await _until(pilot, lambda: not app.is_busy(relabeled))
            assert services.session_store.read(relabeled).revision == "transcript.r3.jsonl"
            app.refresh_view()
            await pilot.pause()
            assert not _button(app, "library-rename").disabled
            assert "busy" not in str(_button(app, "library-rename").label)

            services.job_started.clear()
            await run(pilot, "d", "library-rediarize")
            await _until(
                pilot, lambda: not app.is_busy(relabeled) and services.job_started.is_set()
            )
            assert ("diarization", relabeled) in services.actions

    try:
        asyncio.run(exercise())
    finally:
        services.release_job.set()


def test_library_play_refusal_shows_a_notice(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    services.play_error = ValueError("source audio is missing or invalid")
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            await pilot.press("p")
            await _until(pilot, lambda: "Could not play" in _notices(app))

    asyncio.run(exercise())


@pytest.mark.parametrize("by", ["key", "click"])
def test_library_rename_export_and_delete_by_key_and_click(tmp_path, by):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    app = HubApp(services)
    live = sessions["relabeled"]
    output = tmp_path / "exports"

    async def run(pilot, key, button_id):
        if by == "key":
            await pilot.press(key)
        else:
            await pilot.click(f"#{button_id}")

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            await run(pilot, "r", "library-rename")
            await _until(pilot, lambda: isinstance(app.screen, RenameDialog))
            await pilot.press(*"Alice", "enter")
            await _until(
                pilot,
                lambda: "Alice" in services.session_store.read(live).talk_time,
            )
            await _until(
                pilot,
                lambda: "Alice" in app.screen.query_one("#library-speakers", Static).render().plain,
            )

            await run(pilot, "x", "library-export")
            await _until(pilot, lambda: isinstance(app.screen, ExportDialog))
            text = _screen_text(app)
            for word in ("md", "jsonl", "srt", "txt", "[esc] Cancel", "[enter] Export"):
                assert word in text
            folder = app.screen.query_one("#export-folder", Input)
            assert folder.value == "~/Documents"
            if by == "key":
                await pilot.press("tab")
            else:
                await pilot.click("#export-format-jsonl")
            assert app.screen.export_format == "jsonl"
            assert "(●) jsonl" in _screen_text(app)
            folder.value = str(output)
            await pilot.press("enter")
            await _until(pilot, lambda: (output / f"{live}.jsonl").is_file())
            await _until(pilot, lambda: str(output / f"{live}.jsonl") in _notices(app))

            await run(pilot, "delete", "library-delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            assert live in str(app.screen.query_one("#quit-prompt", Static).render())
            await pilot.click("#cancel-quit")
            await pilot.pause()
            assert (root / live).is_dir()

            await run(pilot, "delete", "library-delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.click("#confirm-quit")
            await _until(pilot, lambda: not (root / live).exists())
            await _until(pilot, lambda: len(app.library_screen.entries) == 3)

    asyncio.run(exercise())


def test_library_export_dialog_escape_cancels(tmp_path):
    root, _sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            await pilot.press("x")
            await _until(pilot, lambda: isinstance(app.screen, ExportDialog))
            await pilot.click("#dialog-cancel")
            await _until(pilot, lambda: not isinstance(app.screen, ExportDialog))
            await pilot.press("x")
            await _until(pilot, lambda: isinstance(app.screen, ExportDialog))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, ExportDialog))

    asyncio.run(exercise())


def test_library_job_rows_complete_fail_and_cancel(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    sources = tmp_path / "sources"
    done = FakeJob("file-1", sources / "done.mp3", percent=60)
    done.progress = FileJobProgress(
        "transcribe",
        60,
        None,
        (TranscriptLine(0.0, 1.0, "", "file", "speaker-1", "Speaker 1", "juliet kilo lima"),),
    )
    failing = FakeJob("file-2", sources / "broken.mp3", state="queued", percent=0)
    cancelled = FakeJob("file-3", sources / "dropped.mp3", state="queued", percent=0)
    services.jobs.extend((done, failing, cancelled))
    app = HubApp(services)
    screen = app.library_screen

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            await _until(pilot, lambda: len(screen.entries) == 7)
            names = [entry.job_name for entry in screen.entries[:3]]
            assert sorted(names) == ["broken.mp3", "done.mp3", "dropped.mp3"]
            assert screen.select_entry("job:file-1")
            app.refresh_view()
            await pilot.pause()
            text = _screen_text(app)
            assert "transcribing 60%" in text
            assert "juliet kilo lima" in text

            # The completed job becomes its session row and keeps the selection.
            new_id = _write_file_session(root, tmp_path, name="done.mp3")
            done.session_id = new_id
            done.state = "completed"
            await _until(pilot, lambda: screen.selected_id == new_id)
            assert not any(entry.entry_id == "job:file-1" for entry in screen.entries)

            # A failed job shows its failed glyph and word; del removes its row.
            failing.state = "failed"
            failing.error = "file job failed: RuntimeError"
            await _until(pilot, lambda: any(FAILED in row for row in _rows(app)))
            screen.select_entry("job:file-2")
            await pilot.press("delete")
            await _until(pilot, lambda: not any(e.entry_id == "job:file-2" for e in screen.entries))

            # del on a queued job asks, then cancels it; the cancelled row goes away.
            assert screen.select_entry("job:file-3")
            await pilot.press("delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.click("#cancel-quit")
            await pilot.pause()
            assert not cancelled.cancel_requested
            await pilot.press("delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.click("#confirm-quit")
            await _until(pilot, lambda: cancelled.cancel_requested)
            cancelled.state = "cancelled"
            await _until(pilot, lambda: not any(e.entry_id == "job:file-3" for e in screen.entries))

    asyncio.run(exercise())


def test_library_revision_job_on_a_session_row_under_a_search(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    app = HubApp(services)
    screen = app.library_screen
    live = sessions["live"]
    mic = root / live / "mic.flac"

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            job = await asyncio.to_thread(screen.submit_file, mic)
            assert job is not None
            assert app.is_busy(live)
            # A revision job adds no row; its session row shows the job.
            await _until(pilot, lambda: screen.entry(live) and screen.entry(live).job is job)
            assert len(screen.entries) == 4

            # The search "mic.flac" matches only the job source name.
            await pilot.press("slash", *"mic.flac")
            await _until(pilot, lambda: [e.entry_id for e in screen.entries] == [live])
            assert screen.selected_id == live
            assert "queued" in _rows(app)[0]

            job.state = "running"
            job.progress = FileJobProgress("transcribe", 37, None, ())
            await _until(pilot, lambda: "37%" in _rows(app)[0])
            app.refresh_view()
            await pilot.pause()
            assert "busy" in str(_button(app, "library-delete").label)

            # del cancels the job; it does not delete the session.
            await pilot.press("escape")
            await _until(pilot, lambda: len(screen.entries) == 4)
            screen.select_session(live)
            await pilot.press("delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            assert "mic.flac" in str(app.screen.query_one("#quit-prompt", Static).render())
            await pilot.click("#confirm-quit")
            await _until(pilot, lambda: job.cancel_requested)
            job.state = "cancelled"
            await _until(pilot, lambda: not app.is_busy(live))
            assert (root / live).is_dir()
            await _until(pilot, lambda: screen.entry(live).job is None)

            # A second job on the same session runs to completion and releases.
            second = await asyncio.to_thread(screen.submit_file, mic)
            assert app.is_busy(live)
            await pilot.press("slash", *"mic.flac")
            await _until(pilot, lambda: [e.entry_id for e in screen.entries] == [live])
            second.state = "running"
            second.progress = FileJobProgress("transcribe", 80, None, ())
            await _until(pilot, lambda: "80%" in _rows(app)[0])
            second.session_id = live
            second.state = "completed"
            await _until(pilot, lambda: not app.is_busy(live))
            await _until(pilot, lambda: screen.entries == () or "%" not in _rows(app)[0])

    asyncio.run(exercise())


def test_library_retranscribe_and_file_revision_race_one_starts(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    app = HubApp(services)
    screen = app.library_screen
    target = sessions["relabeled"]
    mic = root / target / "mic.flac"

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            barrier = threading.Barrier(2)
            results = {}

            def retranscribe():
                barrier.wait()
                app.call_from_thread(screen.action_session_retranscribe)

            def submit():
                barrier.wait()
                results["job"] = screen.submit_file(mic)

            threads = [threading.Thread(target=retranscribe), threading.Thread(target=submit)]
            for thread in threads:
                thread.start()
            await asyncio.to_thread(lambda: [thread.join(5) for thread in threads])
            await pilot.pause(0.1)

            started_retranscribe = services.job_started.wait(0.5)
            started_file = results["job"] is not None
            assert started_retranscribe != started_file
            await _until(pilot, lambda: "session busy" in _notices(app))
            assert app.is_busy(target)

            # The mark stays until its owner ends.
            await pilot.pause(0.1)
            assert app.is_busy(target)
            if started_file:
                results["job"].state = "completed"
                results["job"].session_id = target
            else:
                services.release_job.set()
            await _until(pilot, lambda: not app.is_busy(target))

    try:
        asyncio.run(exercise())
    finally:
        services.release_job.set()


def test_library_screen_has_no_unawaited_coroutines(tmp_path):
    root, _sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            for _ in range(3):
                app.library_screen.load_sessions()
                await pilot.press("2", "down", "1", "2", "down")
            await _until(pilot, lambda: len(app.library_screen.entries) == 4)
            # Select each entry in one tick: each exclusive detail read replaces the last
            # one before it starts.
            screen = app.library_screen
            for _ in range(3):
                for entry in screen.entries:
                    screen.select_entry(entry.entry_id)
            await _until(pilot, lambda: screen.detail is not None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(exercise())
        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)]


# V2: Play of a file session through HubServices


class _Decoder:
    def __init__(self):
        self.paths: list[Path] = []

    def __call__(self, path):
        self.paths.append(Path(path))
        return DecodedAudio(np.full(8_000, 0.25, dtype=np.float32), 16_000, 0.5)


def _play_services(tmp_path, monkeypatch, player_factory):
    monkeypatch.setattr(tempfile, "tempdir", str(_private_tmp(tmp_path)))
    root = tmp_path / "sessions"
    session_id = _write_file_session(root, tmp_path)
    store = SessionStore(root)
    decoder = _Decoder()
    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=store,
        player_factory=player_factory,
        media_decoder=decoder,
    )
    return services, store, session_id, decoder


def _private_tmp(tmp_path: Path) -> Path:
    path = tmp_path / "private-tmp"
    path.mkdir(exist_ok=True)
    return path


def test_library_play_of_a_file_session_decodes_the_source_and_removes_its_temp_file(
    tmp_path, monkeypatch
):
    player = FakePlayer()
    commands = []

    def start_player(command):
        commands.append(command)
        return player

    services, store, session_id, decoder = _play_services(tmp_path, monkeypatch, start_player)
    services.toggle_session_playback(session_id)

    assert decoder.paths == [store.source_audio(session_id)]
    played = Path(commands[0][1])
    assert commands[0][0] == "pw-play"
    assert played.parent == _private_tmp(tmp_path)
    samples, rate = sf.read(played, dtype="float32")
    assert rate == 16_000 and samples.size == 8_000
    assert np.allclose(samples, 0.25, atol=0.001)

    services.toggle_session_playback(session_id)
    assert player.terminated
    deadline = time.monotonic() + 2
    while played.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not played.exists()


def test_library_play_of_a_file_session_removes_its_temp_file_after_a_play_failure(
    tmp_path, monkeypatch
):
    def failing_player(command):
        raise OSError("pw-play is missing")

    services, _store, session_id, decoder = _play_services(tmp_path, monkeypatch, failing_player)
    with pytest.raises(OSError):
        services.toggle_session_playback(session_id)
    assert decoder.paths
    assert list(_private_tmp(tmp_path).iterdir()) == []


def test_library_play_refuses_an_invalid_source_file(tmp_path, monkeypatch):
    services, store, session_id, decoder = _play_services(
        tmp_path, monkeypatch, lambda command: FakePlayer()
    )
    metadata_path = store.root / session_id / "session.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_file"] = "../outside.wav"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(SessionSourceError):
        services.toggle_session_playback(session_id)
    assert decoder.paths == []
    assert list(_private_tmp(tmp_path).iterdir()) == []


def test_library_play_notice_for_an_invalid_source_file(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    session_id = _write_file_session(root, tmp_path)
    metadata_path = root / session_id / "session.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_file"] = "../outside.wav"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(root),
        player_factory=lambda command: FakePlayer(),
        media_decoder=_Decoder(),
    )
    app = HubApp(services)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 1)
            await pilot.press("p")
            await _until(pilot, lambda: "source audio is missing or invalid" in _notices(app))

    asyncio.run(exercise())


def test_library_layout_frames_rows_state_rule_and_transcript_colours(tmp_path):
    root, _sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4)
            listing = app.screen.query_one("#library-list-frame")
            detail = app.screen.query_one("#library-detail-frame")
            assert listing.styles.border.top[0] == "round"
            assert detail.styles.border.top[0] == "round"
            assert listing.region.x < detail.region.x
            assert listing.region.y == detail.region.y
            assert listing.region.height == detail.region.height

            # Each row stays on one line, the interrupted one too.
            rows = app.screen.query_one("#library-list", Static)
            assert rows.region.height == len(app.library_screen.entries)

            # The label state sits right of the title on the same row.
            title = app.screen.query_one("#library-detail-title", Static)
            state = app.screen.query_one("#library-detail-state", Static)
            assert title.region.y == state.region.y
            assert state.region.right == detail.content_region.right

            # The rule spans the detail and the transcript follows it.
            rule = app.screen.query_one("#library-rule")
            transcript = app.screen.query_one("#library-transcript")
            assert rule.region.width == detail.content_region.width
            assert rule.region.y < transcript.region.y
            assert app.screen.query_one("#library-actions-4").region.y < rule.region.y

            # A speaker name in the transcript is bold in its speaker colour.
            content = app.screen.query_one("#transcript-scroll-content", Static)
            lines = content.render_lines(content.region.reset_offset)
            segments = [segment for strip in lines for segment in strip]
            speaker = next(segment for segment in segments if segment.text.strip() == "Speaker 1")
            assert speaker.style.bold
            assert speaker.style.color.triplet == (255, 175, 95)

    asyncio.run(exercise())


def test_library_storage_card_shortens_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root, _sessions = _library(tmp_path)
    app = HubApp(FakeServices(root))

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_library(pilot, app, 4, detail=False)
            assert "~/sessions" in _card(app)
            assert str(tmp_path) not in _card(app)

    asyncio.run(exercise())
