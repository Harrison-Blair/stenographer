# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Transcribe a file dialog of the Library."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from textual.widgets import Input

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.library_screen import LibraryScreen
from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.transcribe_dialog import TranscribeDialog
from stenographer.lib.config.models import Config
from stenographer.lib.files.engine import FilesEngine
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder
from stenographer.lib.sessions import SessionStore
from tests.cli.hub.test_library import FakeServices, _library, _rows, _screen_text, _until
from tests.cli.hub.test_session_jobs import FakePlatform
from tests.lib.files.test_engine import FakeAsrProcess, FakeAsrTransport, FakeSegmenter


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class RecordingServices(FakeServices):
    """Fake Library services that also keep the options of each submit."""

    def __init__(self, sessions_root: Path):
        super().__init__(sessions_root)
        self.submitted_options: list[dict] = []

    def submit_file(self, path, **options):
        self.submitted_options.append(options)
        return super().submit_file(path, **options)


def _write_audio(path: Path, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.full(16_000 * seconds, 0.1, dtype=np.float32), 16_000)
    return path


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "meetings").mkdir(parents=True)
    _write_audio(home / "alpha.wav", 2)
    _write_audio(home / "bravo.flac", 75)
    _write_audio(home / "meetings" / "charlie.wav", 1)
    (home / "notes.txt").write_text("not audio", encoding="utf-8")
    (home / ".cache").mkdir()
    return home


def _list_rows(app: HubApp) -> list[str]:
    return app.screen.query_one("#transcribe-list").render().plain.splitlines()


def _dialog(app: HubApp) -> TranscribeDialog:
    assert isinstance(app.screen, TranscribeDialog)
    return app.screen


async def _open_dialog(pilot, app: HubApp) -> TranscribeDialog:
    await pilot.press("2")
    await _until(pilot, lambda: app.library_screen.loaded, "library did not load")
    await pilot.press("n")
    await _until(pilot, lambda: isinstance(app.screen, TranscribeDialog), "dialog did not open")
    await pilot.pause()
    return app.screen


async def _search(pilot, text: str) -> None:
    await pilot.press("slash", *text, "enter")
    await pilot.pause()


def test_transcribe_dialog_browses_the_home_folder_and_searches(tmp_path):
    home = _home(tmp_path)
    app = HubApp(RecordingServices(tmp_path / "sessions"), files_home=home)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            dialog = await _open_dialog(pilot, app)
            assert dialog.directory == home
            text = _screen_text(app)
            for label in (
                "Transcribe a file",
                "[/] search",
                "Separate speakers",
                "[s] (●) on",
                "[c] Speaker count",
                "auto",
                "Refine text",
                "[r] ( ) off",
                "[esc] Cancel",
                "[enter] Transcribe",
            ):
                assert label in text, label
            assert "Language" not in text
            rows = _list_rows(app)
            assert rows[0].strip() == ".."
            assert rows[1] == "▶ meetings/"
            assert rows[2].startswith("  alpha.wav") and rows[2].endswith("0:02")
            assert rows[3].startswith("  bravo.flac") and rows[3].endswith("1:15")
            assert len(rows) == 4  # no text file, no hidden folder

            # enter opens the selected folder; ``..`` goes back up.
            await pilot.press("enter")
            assert dialog.directory == home / "meetings"
            assert "~/meetings" in _screen_text(app)
            assert any("charlie.wav" in row for row in _list_rows(app))
            await pilot.press("up", "enter")
            assert dialog.directory == home

            # ``/`` filters the folder by name; escape clears the search first.
            await _search(pilot, "BRA")
            assert [row.strip("▶ ").split()[0] for row in _list_rows(app)] == ["..", "bravo.flac"]
            assert _list_rows(app)[1].startswith("▶ bravo.flac")
            await pilot.press("escape")
            assert isinstance(app.screen, TranscribeDialog)
            assert len(_list_rows(app)) == 4
            await pilot.press("escape")
            await _until(pilot, lambda: isinstance(app.screen, LibraryScreen))
            assert app.services.jobs == []

    asyncio.run(exercise())


@pytest.mark.parametrize("by", ("key", "click"))
def test_transcribe_options_and_an_invalid_speaker_count(tmp_path, by):
    home = _home(tmp_path)
    services = RecordingServices(tmp_path / "sessions")
    app = HubApp(services, files_home=home)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_dialog(pilot, app)
            await pilot.press("down")
            if by == "key":
                await pilot.press("s", "r", "c")
            else:
                await pilot.click("#transcribe-speakers")
                await pilot.click("#transcribe-refine")
                await pilot.click("#transcribe-count-button")
            text = _screen_text(app)
            assert "[s] ( ) off" in text and "[r] (●) on" in text
            count = app.screen.query_one("#transcribe-count", Input)
            assert app.screen.focused is count

            for bad in ("zero", "0", "-2", "1.5"):
                count.value = bad
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, TranscribeDialog)
                assert "✗ Speaker count must be auto or a whole number above 0" in _screen_text(app)
            assert services.jobs == []

            count.value = "3"
            await pilot.pause()
            assert "✗" not in _screen_text(app)
            await pilot.press("enter")
            await _until(pilot, lambda: len(services.jobs) == 1, "no job was queued")
            job = services.jobs[0]
            assert job.options.path == home / "alpha.wav"
            assert services.submitted_options == [
                {"diarize": False, "speaker_count": 3, "refine": True}
            ]

    asyncio.run(exercise())


def test_transcribe_queues_one_job_and_the_library_selects_its_row(tmp_path):
    root, _sessions = _library(tmp_path)
    home = _home(tmp_path)
    services = RecordingServices(root)
    app = HubApp(services, files_home=home)
    screen = app.library_screen

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_dialog(pilot, app)
            await pilot.press("down", "down", "enter")
            await _until(pilot, lambda: isinstance(app.screen, LibraryScreen))
            await _until(pilot, lambda: screen.selected_id == "job:file-1", "row not selected")
            assert [job.options.path for job in services.jobs] == [home / "bravo.flac"]
            assert services.submitted_options == [
                {"diarize": True, "speaker_count": None, "refine": False}
            ]
            assert len(screen.entries) == 5
            rows = _rows(app)
            assert rows[0].startswith("▶") and "queued" in rows[0] and "bravo.flac" in rows[0]

    asyncio.run(exercise())


def _engine_app(tmp_path: Path, home: Path, *, decoder=None) -> tuple[HubApp, Path]:
    data = tmp_path / "data"
    sessions = data / "sessions"

    def make_engine(config, *, platform):
        return FilesEngine(
            config,
            data_dir=data,
            decoder=decoder or SubprocessFfmpegDecoder(),
            transport=FakeAsrTransport(FakeAsrProcess()),
            segmenter_factory=FakeSegmenter,
            clock=lambda: datetime(2026, 10, 27, 9, 0, tzinfo=UTC),
        )

    services = HubServices(
        Config.defaults(),
        FakePlatform(data),
        session_store=SessionStore(sessions),
        files_engine_factory=make_engine,
    )
    return HubApp(services, files_home=home), sessions


def _recording(tmp_path: Path) -> Path:
    writer = SessionWriter.open(tmp_path / "data", datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    writer.write_audio("mic", np.full(32_000, 0.1, dtype=np.float32))
    writer.write_audio("system", np.full(32_000, 0.1, dtype=np.float32))
    writer.append_line(TranscriptLine(0.0, 0.5, "", "system", "speaker-1", "Speaker 1", "alpha"))
    writer.append_line(TranscriptLine(0.2, 0.9, "", "mic", "you", "You", "bravo"))
    writer.close()
    return writer.path


def test_transcribe_with_the_real_engine_revises_a_session_or_makes_a_file_row(tmp_path):
    session = _recording(tmp_path)
    _write_audio(tmp_path / "outside.wav", 2)
    app, sessions = _engine_app(tmp_path, tmp_path)
    screen = app.library_screen
    store = SessionStore(sessions)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_dialog(pilot, app)
            assert len(screen.entries) == 1
            for folder in ("data", "sessions", session.name):
                await _search(pilot, folder)
                await pilot.press("enter")
            await _search(pilot, "system")
            await pilot.press("s", "enter")
            await _until(pilot, lambda: isinstance(app.screen, LibraryScreen))
            await _until(
                pilot,
                lambda: store.read(session.name).revision == "transcript.r2.jsonl",
                "no revision was written",
            )
            # The revision adds no row; its session row stays selected.
            await _until(pilot, lambda: screen.entry(session.name).job is None)
            assert [entry.entry_id for entry in screen.entries] == [session.name]
            assert screen.selected_id == session.name
            assert [path.name for path in sessions.iterdir()] == [session.name]
            assert not app.is_busy(session.name)

            # A file outside the sessions folder makes a new ``file`` row.
            await pilot.press("n")
            await _until(pilot, lambda: isinstance(app.screen, TranscribeDialog))
            await _search(pilot, "outside")
            await pilot.press("s", "enter")
            await _until(pilot, lambda: len(list(sessions.iterdir())) == 2, "no new session")
            new_id = "20261027T090000Z"
            await _until(pilot, lambda: screen.selected_id == new_id, "new session not selected")
            await _until(pilot, lambda: screen.entry(new_id).kind == "file")
            assert len(screen.entries) == 2
            assert "outside.wav" in _rows(app)[0]

    asyncio.run(exercise())


class _NoFfmpeg:
    def available(self):
        return False


def test_transcribe_an_m4a_without_ffmpeg_shows_the_needs_ffmpeg_message(tmp_path):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"not decoded without ffmpeg")
    app, _sessions = _engine_app(tmp_path, tmp_path, decoder=_NoFfmpeg())
    screen = app.library_screen

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_dialog(pilot, app)
            await _search(pilot, "voice")
            await pilot.press("enter")
            await _until(pilot, lambda: "\u00d7 failed · vo" in _rows(app)[0], "no failed row")
            assert screen.selected_entry.job_name == "voice.m4a"
            app.refresh_view()
            await pilot.pause()
            assert "\u00d7 needs ffmpeg" in _screen_text(app)

    asyncio.run(exercise())
