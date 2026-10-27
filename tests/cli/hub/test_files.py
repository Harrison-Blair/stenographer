# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Files section and its background jobs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from rich.color import Color
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.files_view import FilesPanel
from stenographer.lib.files.models import FileJobProgress
from stenographer.lib.live.transcript_line import TranscriptLine


class FakeJob:
    def __init__(self, path: Path, options: dict):
        self.id = f"file-{path.stem}"
        self.options = SimpleNamespace(path=path, **options)
        self.state = "queued"
        self.progress = FileJobProgress("transcribe", 0, None, ())
        self.session_id = None
        self.error = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.state = "cancelled"
        return True


class FakeFilesEngine:
    def __init__(self):
        self.jobs = []
        self.submitted = []
        self.closed = False

    def submit(self, path: Path, **options):
        job = FakeJob(path, options)
        self.jobs.append(job)
        self.submitted.append((path, options))
        return job

    def close(self):
        self.closed = True


class FakeServices:
    def __init__(self, output_folder: Path):
        self.engine = FakeFilesEngine()
        self.recording = False
        self.active_session_id = None

    @property
    def files_jobs(self):
        return tuple(self.engine.jobs)

    @property
    def files_running(self):
        return any(job.state in {"queued", "running"} for job in self.engine.jobs)

    def submit_file(self, path: Path, **options):
        return self.engine.submit(path, **options)

    def cancel_file(self, job):
        return job.cancel()

    def cancel_files(self):
        for job in self.engine.jobs:
            job.cancel()


def _write_audio(path: Path, seconds: int = 2) -> None:
    sf.write(path, np.zeros(16_000 * seconds, dtype=np.float32), 16_000)


def _panel_text(app: HubApp) -> str:
    return app.library_screen.files_panel.display_text()


async def _wait_for(pilot, predicate) -> None:
    for _ in range(50):
        if predicate():
            return
        await pilot.pause(0.02)
    assert predicate()


def test_files_panels_have_board_layout_and_the_engine_card(tmp_path):
    _write_audio(tmp_path / "standup.wav")
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            await pilot.pause()

            browser = app.screen.query_one("#files-browser-scroll", Vertical)
            options = app.screen.query_one("#files-options-scroll", VerticalScroll)
            queue = app.screen.query_one("#files-queue-scroll", VerticalScroll)
            preview = app.screen.query_one("#files-preview-scroll", VerticalScroll)
            main = app.screen.query_one("#files-main")
            right = app.screen.query_one("#files-right")

            for panel in (browser, options, queue, preview):
                assert panel.styles.border.top[0] == "round"
            assert browser.region.x < options.region.x
            assert browser.region.y < preview.region.y
            assert main.region.y + main.region.height <= preview.region.y
            assert abs(browser.region.width - right.region.width) <= 1
            assert abs(options.region.height - queue.region.height) <= 1
            assert main.region.height > preview.region.height
            # A 3:2 split of the column, within the one row that layout rounding takes.
            column = main.region.height + preview.region.height
            assert abs(main.region.height - column * 3 / 5) < 1

            assert app.library_screen.files_open
            assert not app.library_screen.sessions_panel.display
            model = app.screen.query_one("#engine-model", Static).render()
            assert str(model) == "bark-pro-int8"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "panel_id",
    (
        "#files-browser-scroll",
        "#files-options-scroll",
        "#files-queue-scroll",
        "#files-preview-scroll",
    ),
)
def test_files_panel_titles_use_terminal_foreground_and_bold(tmp_path, panel_id):
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            panel = app.screen.query_one(panel_id)
            assert panel.styles.border_title_color.ansi == -1
            assert panel.styles.border_title_style.bold

    asyncio.run(exercise())


def test_files_browser_hint_is_pinned_to_panel_bottom(tmp_path):
    _write_audio(tmp_path / "standup.wav")
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            await pilot.pause()

            panel = app.screen.query_one("#files-browser-scroll")
            hint = app.screen.query_one("#files-browser-hint", Static)
            rows = app.screen.query_one("#files-browser", Static)

            assert panel.styles.border.top[0] == "round"
            assert hint.render().plain == "/ search · enter queue · space select"
            assert rows.region.y < hint.region.y
            assert hint.region.bottom == panel.region.bottom - 1

    asyncio.run(exercise())


def test_files_browser_title_tracks_current_directory(tmp_path):
    recordings = tmp_path / "Recordings"
    recordings.mkdir()
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n", "enter")
            browser = app.screen.query_one("#files-browser-scroll", Vertical)
            assert browser.border_title == "~/Recordings"

    asyncio.run(exercise())


def _recordings_app(tmp_path, monkeypatch, *, with_sessions: bool):
    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.config.models import Config
    from stenographer.lib.platform import current_platform

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    sessions = tmp_path / "data" / "stenographer" / "sessions"
    if with_sessions:
        (sessions / "20261021T120000Z").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    services = HubServices(Config.defaults(), current_platform())
    return HubApp(services, files_home=home), home, sessions


def test_files_browser_starts_in_recordings_folder(tmp_path, monkeypatch):
    app, _home, sessions = _recordings_app(tmp_path, monkeypatch, with_sessions=True)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            assert app.library_screen.files_panel.directory == sessions
            assert "20261021T120000Z/" in _panel_text(app)
            browser = app.screen.query_one("#files-browser-scroll", Vertical)
            assert browser.border_title == str(sessions)
            await pilot.press("up", "enter")
            assert app.library_screen.files_panel.directory == sessions.parent

    asyncio.run(exercise())


def test_files_browser_falls_back_to_home_without_recordings_folder(tmp_path, monkeypatch):
    app, home, sessions = _recordings_app(tmp_path, monkeypatch, with_sessions=False)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            assert app.library_screen.files_panel.directory == home
            browser = app.screen.query_one("#files-browser-scroll", Vertical)
            assert browser.border_title == "~"
            assert not sessions.exists()

    asyncio.run(exercise())


def test_files_browser_durations_use_board_clock_format():
    assert FilesPanel._format_clock(151) == "2:31"
    assert FilesPanel._format_clock(3735) == "1:02:15"


@pytest.mark.parametrize("value", ("[x] diarize", "auto", "[ ] cleanup pass"))
def test_files_chosen_option_values_use_accent_color(tmp_path, value):
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            rendered = app.screen.query_one("#files-options", Static).render()
            assert value in rendered.plain
            start = rendered.plain.index(value)
            styles = [
                span.style.rich_style for span in rendered.spans if span.start <= start < span.end
            ]
            assert styles, f"{value!r} is not styled with the accent color"
            assert styles[0].color is not None
            assert styles[0].color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()

    asyncio.run(exercise())


def test_files_preview_uses_distinct_shared_speaker_colors(tmp_path):
    path = tmp_path / "standup.wav"
    _write_audio(path)
    job = FakeJob(path, {"diarize": True})
    job.progress = FileJobProgress(
        "diarize",
        55,
        17.5,
        (
            TranscriptLine(4.0, 5.0, "", "file", "speaker-1", "Speaker 1", "sample alpha"),
            TranscriptLine(6.0, 7.0, "", "file", "speaker-2", "Speaker 2", "sample beta"),
        ),
    )
    services = FakeServices(tmp_path / "exports")
    services.engine.jobs.append(job)
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            app.library_screen.refresh_files()
            await pilot.pause()

            preview = app.screen.query_one("#files-preview", Static).render()
            assert "Speaker 1" in preview.plain
            assert "Speaker 2" in preview.plain
            styles = {}
            for label in ("Speaker 1", "Speaker 2"):
                offset = preview.plain.index(label)
                styles[label] = next(
                    span.style.rich_style
                    for span in preview.spans
                    if span.start <= offset < span.end
                )
            assert styles["Speaker 1"].color != styles["Speaker 2"].color
            assert (
                styles["Speaker 1"].color.get_truecolor() == Color.parse("#ffaf5f").get_truecolor()
            )
            assert (
                styles["Speaker 2"].color.get_truecolor() == Color.parse("#d787ff").get_truecolor()
            )
            assert all(style.bold for style in styles.values())
            assert all(
                style.bgcolor is None or style.bgcolor.is_default for style in styles.values()
            )

    asyncio.run(exercise())


def test_files_options_queue_preview_and_key_hints_match_board(tmp_path):
    path = tmp_path / "standup.wav"
    _write_audio(path)
    job = FakeJob(path, {"diarize": True})
    job.state = "running"
    line = TranscriptLine(4.0, 5.0, "", "file", "speaker-1", "Speaker 1", "fixture words")
    job.progress = FileJobProgress("diarize", 55, 17.5, (line,))
    services = FakeServices(tmp_path / "exports")
    services.engine.jobs.append(job)
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "n")
            app.library_screen.refresh_files()
            await pilot.pause()

            options = app.screen.query_one("#files-options", Static).render()
            assert "[x] diarize" in options.plain and "count auto" in options.plain
            assert "refine        [ ] cleanup pass" in options.plain
            assert "output" not in options.plain
            assert "save to" not in options.plain
            assert "[ ] on" not in options.plain

            content = _panel_text(app)
            assert "55%" in content and "▕" in content and "eta 0:17" in content
            assert "transcribe ✓ · diarize … · save" in content

            preview_panel = app.screen.query_one("#files-preview-scroll", VerticalScroll)
            assert preview_panel.border_title == "preview · standup"
            preview = app.screen.query_one("#files-preview", Static).render()
            assert "00:00:04" in preview.plain and "Speaker 1" in preview.plain
            assert "Speaker 1\u00a0 fixture words" in preview.plain
            label_style = next(
                span.style
                for span in preview.spans
                if span.start <= preview.plain.index("Speaker 1") < span.end
            ).rich_style
            assert label_style.bold
            assert label_style.color is not None
            assert label_style.color.get_truecolor() == Color.parse("#ffaf5f").get_truecolor()
            assert label_style.bgcolor is None or label_style.bgcolor.is_default

            hints = app.screen.query_one("#key-hints", Static).render().plain
            assert "open result" not in hints
            assert hints.endswith("esc back · 1 2 3 screens · ? help · q quit")

    asyncio.run(exercise())


def test_hub_services_create_the_file_engine_lazily_and_close_it(tmp_path):
    from stenographer.cli.hub.services import HubServices
    from stenographer.lib.config.models import Config

    engines = []

    def make_engine(_config, *, platform):
        assert platform.data_dir({}, Path.home()) == tmp_path
        engine = FakeFilesEngine()
        engines.append(engine)
        return engine

    platform = SimpleNamespace(data_dir=lambda _env, _home: tmp_path)
    services = HubServices(Config.defaults(), platform, files_engine_factory=make_engine)

    assert services.files_jobs == ()
    assert not services.files_running
    assert not hasattr(services, "files_output_folder")
    job = services.submit_file(tmp_path / "voice.wav", diarize=False)
    assert len(engines) == 1
    assert services.files_jobs == (job,)
    assert services.files_running
    assert engines[0].submitted == [(tmp_path / "voice.wav", {"diarize": False})]

    assert services.cancel_file(job)
    assert not services.files_running
    assert not hasattr(services, "open_files_result")
    services.close_files()
    assert engines[0].closed
    assert services.files_jobs == ()


def test_pilot_file_browser_search_and_multi_select_queue(tmp_path):
    _write_audio(tmp_path / "alpha.wav")
    _write_audio(tmp_path / "beta.wav", seconds=3)
    services = FakeServices(tmp_path / "exports")
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "n")
            text = _panel_text(app)
            browser = app.screen.query_one("#files-browser-scroll", Vertical)
            browser_text = app.screen.query_one("#files-browser", Static).render().plain
            assert browser.border_title == "~"
            assert str(tmp_path) not in browser_text
            assert "alpha.wav" in text and "0:02" in text
            assert "beta.wav" in text and "0:03" in text

            await pilot.press("/")
            search = app.screen.query_one("#config-prompt-input", Input)
            search.value = "beta"
            await pilot.press("enter")
            text = _panel_text(app)
            assert "beta.wav" in text
            assert "alpha.wav" not in text

            await pilot.press("/")
            search = app.screen.query_one("#config-prompt-input", Input)
            search.value = ""
            await pilot.press("enter")
            await pilot.press("space", "down", "space", "enter")
            await _wait_for(pilot, lambda: len(services.engine.submitted) == 2)
            assert [path.name for path, _ in services.engine.submitted] == [
                "alpha.wav",
                "beta.wav",
            ]
            assert all(options["diarize"] for _, options in services.engine.submitted)
            assert all(not options["refine"] for _, options in services.engine.submitted)
            assert all(
                set(options) == {"diarize", "speaker_count", "refine"}
                for _, options in services.engine.submitted
            )

    asyncio.run(exercise())


def test_pilot_file_browser_enters_subfolders_and_parent(tmp_path):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    _write_audio(recordings / "inside.wav")
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "n", "enter")
            assert app.library_screen.files_panel.directory == recordings
            assert app.library_screen.files_panel.selected_entry.path == recordings / "inside.wav"
            await pilot.press("up", "enter")
            assert app.library_screen.files_panel.directory == tmp_path

    asyncio.run(exercise())


def test_pilot_file_options_can_be_changed(tmp_path):
    services = FakeServices(tmp_path / "exports")
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "n", "o", "space", "down", "enter")
            speaker_count = app.screen.query_one("#config-prompt-input", Input)
            speaker_count.value = "2"
            await pilot.press("enter")
            await pilot.press("down", "space")

            assert not app.library_screen.files_panel.diarize
            assert app.library_screen.files_panel.speaker_count == 2
            assert app.library_screen.files_panel.refine
            options = app.screen.query_one("#files-options", Static).render().plain
            assert "speakers      [ ] diarize   count 2" in options
            assert "refine        [x] cleanup pass" in options
            assert "output" not in options

    asyncio.run(exercise())


def test_pilot_queue_progress_preview_and_cancel(tmp_path):
    _write_audio(tmp_path / "alpha.wav")
    _write_audio(tmp_path / "beta.wav")
    services = FakeServices(tmp_path / "exports")
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "n", "space", "down", "space", "enter")
            await _wait_for(pilot, lambda: len(services.engine.jobs) == 2)
            await pilot.press("tab", "up")
            first, second = services.engine.jobs
            line = TranscriptLine(1.0, 2.0, "", "file", "speaker-1", "Speaker 1", "fixture line")
            first.state = "running"
            first.progress = FileJobProgress("diarize", 55, 17.5, (line,))
            await pilot.press("3")
            await pilot.pause(0.05)
            assert services.files_running
            assert not first.cancelled and not second.cancelled
            await pilot.press("2", "n")
            app.library_screen.refresh_files()
            text = _panel_text(app)
            assert "55%" in text and "diarize" in text and "17" in text
            assert "Speaker 1" in text and "fixture line" in text

            first.state = "completed"
            first.session_id = "20261021T120000Z"
            await pilot.press("down", "x")
            assert second.cancelled

    asyncio.run(exercise())
