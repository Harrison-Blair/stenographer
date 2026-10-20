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
from textual.containers import VerticalScroll
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
        self.output_path = None
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
        self.files_output_folder = output_folder
        self.recording = False
        self.active_session_id = None
        self.opened_folders = []

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

    def open_files_result(self, output_path: Path):
        self.opened_folders.append(output_path.parent)
        return True

    def cancel_files(self):
        for job in self.engine.jobs:
            job.cancel()


def _write_audio(path: Path, seconds: int = 2) -> None:
    sf.write(path, np.zeros(16_000 * seconds, dtype=np.float32), 16_000)


def _panel_text(app: HubApp) -> str:
    return app.files_panel.display_text()


async def _wait_for(pilot, predicate) -> None:
    for _ in range(50):
        if predicate():
            return
        await pilot.pause(0.02)
    assert predicate()


def test_files_panels_have_board_layout_and_files_sidebar_card(tmp_path):
    _write_audio(tmp_path / "standup.wav")
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            browser = app.query_one("#files-browser-scroll", VerticalScroll)
            options = app.query_one("#files-options-scroll", VerticalScroll)
            queue = app.query_one("#files-queue-scroll", VerticalScroll)
            preview = app.query_one("#files-preview-scroll", VerticalScroll)
            main = app.query_one("#files-main")
            right = app.query_one("#files-right")

            for panel in (browser, options, queue, preview):
                assert panel.styles.border.top[0] == "round"
            assert browser.region.x < options.region.x
            assert browser.region.y < preview.region.y
            assert main.region.y + main.region.height <= preview.region.y
            assert abs(browser.region.width - right.region.width) <= 1
            assert abs(options.region.height - queue.region.height) <= 1
            assert main.region.height > preview.region.height
            assert abs(main.region.height * 2 - preview.region.height * 3) <= 3

            card = str(app.query_one("#sidebar-card", Static).render())
            assert "engine" in card
            model = (
                app._current_config()
                .asr.model.rsplit("/", 1)[-1]
                .removeprefix("faster-whisper-")
                .removesuffix("-ct2")
            )
            assert model in card
            assert app._current_config().asr.compute_type in card
            assert "cpu" in card

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
            await pilot.press("2")
            panel = app.query_one(panel_id, VerticalScroll)
            assert panel.styles.border_title_color.ansi == -1
            assert panel.styles.border_title_style.bold

    asyncio.run(exercise())


def test_files_browser_title_tracks_current_directory(tmp_path):
    recordings = tmp_path / "Recordings"
    recordings.mkdir()
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2", "enter")
            browser = app.query_one("#files-browser-scroll", VerticalScroll)
            assert browser.border_title == "~/Recordings"

    asyncio.run(exercise())


def test_files_browser_durations_use_board_clock_format():
    assert FilesPanel._format_clock(151) == "2:31"
    assert FilesPanel._format_clock(3735) == "1:02:15"


@pytest.mark.parametrize("value", ("[x] diarize", "auto", "[ ] cleanup pass", "md"))
def test_files_chosen_option_values_use_accent_color(tmp_path, value):
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            rendered = app.query_one("#files-options", Static).render()
            assert value in rendered.plain
            start = rendered.plain.index(value)
            styles = [
                span.style.rich_style for span in rendered.spans if span.start <= start < span.end
            ]
            assert styles, f"{value!r} is not styled with the accent color"
            assert styles[0].color is not None
            assert styles[0].color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()

    asyncio.run(exercise())


def test_files_options_queue_preview_and_key_hints_match_board(tmp_path):
    path = tmp_path / "standup.wav"
    _write_audio(path)
    job = FakeJob(path, {"diarize": True})
    job.state = "running"
    line = TranscriptLine(4.0, 5.0, "", "file", "speaker-1", "Speaker 1", "fixture words")
    job.progress = FileJobProgress("diarize", 55, 17.5, (line,))
    job.output_path = tmp_path / "exports" / "standup.md"
    services = FakeServices(tmp_path / "exports")
    services.engine.jobs.append(job)
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("2")
            app._refresh_files_view()
            await pilot.pause()

            options = app.query_one("#files-options", Static).render()
            assert "[x] diarize" in options.plain and "count auto" in options.plain
            assert "refine        [ ] cleanup pass" in options.plain
            assert "output        md · jsonl · srt · txt" in options.plain
            assert "save to" in options.plain
            assert "[ ] on" not in options.plain
            format_offset = options.plain.index("output        ") + len("output        ")
            format_style = next(
                span.style for span in options.spans if span.start <= format_offset < span.end
            ).rich_style
            assert format_style.bold
            assert format_style.color is not None
            assert format_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()

            content = _panel_text(app)
            assert "55%" in content and "▕" in content and "eta 0:17" in content
            assert "transcribe ✓ · diarize … · save" in content

            preview_panel = app.query_one("#files-preview-scroll", VerticalScroll)
            assert preview_panel.border_title == "preview · standup"
            preview = app.query_one("#files-preview", Static).render()
            assert "00:00:04" in preview.plain and "Speaker 1" in preview.plain
            assert "Speaker 1\u00a0 fixture words" in preview.plain
            label_style = next(
                span.style
                for span in preview.spans
                if span.start <= preview.plain.index("Speaker 1") < span.end
            ).rich_style
            assert label_style.bold
            assert label_style.color is not None
            assert label_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
            assert label_style.bgcolor is None or label_style.bgcolor.is_default

            hints = app.query_one("#key-hints", Static).render().plain
            assert "e open result" in hints
            assert "1-6 sections" in hints

    asyncio.run(exercise())


def test_hub_services_create_the_file_engine_lazily_and_close_it(tmp_path, monkeypatch):
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
    assert services.files_output_folder == tmp_path / "files"
    job = services.submit_file(tmp_path / "voice.wav", output_format="srt")
    assert len(engines) == 1
    assert services.files_jobs == (job,)
    assert services.files_running
    assert engines[0].submitted == [(tmp_path / "voice.wav", {"output_format": "srt"})]

    assert services.cancel_file(job)
    assert not services.files_running
    launched = []
    monkeypatch.setattr(
        "stenographer.cli.hub.services.subprocess.Popen",
        lambda command, **options: launched.append((command, options)),
    )
    output_path = tmp_path / "exports" / "voice.srt"
    assert services.open_files_result(output_path)
    assert launched[0][0] == ["xdg-open", str(output_path.parent)]
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
            await pilot.press("2")
            text = _panel_text(app)
            browser = app.query_one("#files-browser-scroll", VerticalScroll)
            browser_text = app.query_one("#files-browser", Static).render().plain
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
            assert all(options["output_format"] == "md" for _, options in services.engine.submitted)

    asyncio.run(exercise())


def test_pilot_file_browser_enters_subfolders_and_parent(tmp_path):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    _write_audio(recordings / "inside.wav")
    app = HubApp(FakeServices(tmp_path / "exports"), files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "enter")
            assert app.files_panel.directory == recordings
            assert app.files_panel.selected_entry.path == recordings / "inside.wav"
            await pilot.press("up", "enter")
            assert app.files_panel.directory == tmp_path

    asyncio.run(exercise())


def test_pilot_file_options_can_be_changed(tmp_path):
    services = FakeServices(tmp_path / "exports")
    app = HubApp(services, files_home=tmp_path)
    output_folder = tmp_path / "custom-output"

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "o", "space", "down", "enter")
            speaker_count = app.screen.query_one("#config-prompt-input", Input)
            speaker_count.value = "2"
            await pilot.press("enter")
            await pilot.press("down", "space", "down", "space", "down", "enter")
            folder = app.screen.query_one("#config-prompt-input", Input)
            folder.value = str(output_folder)
            await pilot.press("enter")

            assert not app.files_panel.diarize
            assert app.files_panel.speaker_count == 2
            assert app.files_panel.refine
            assert app.files_panel.output_format == "jsonl"
            assert app.files_panel.output_folder == output_folder
            options = app.query_one("#files-options", Static).render().plain
            assert "speakers      [ ] diarize   count 2" in options
            assert "refine        [x] cleanup pass" in options
            assert "output        md · jsonl · srt · txt" in options

    asyncio.run(exercise())


def test_pilot_queue_progress_preview_cancel_and_open_result_folder(tmp_path):
    _write_audio(tmp_path / "alpha.wav")
    _write_audio(tmp_path / "beta.wav")
    services = FakeServices(tmp_path / "exports")
    app = HubApp(services, files_home=tmp_path)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("2", "space", "down", "space", "enter")
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
            await pilot.press("2")
            app._refresh_files_view()
            text = _panel_text(app)
            assert "55%" in text and "diarize" in text and "17" in text
            assert "Speaker 1" in text and "fixture line" in text

            output_path = tmp_path / "exports" / "alpha.md"
            first.state = "completed"
            first.output_path = output_path
            await pilot.press("e")
            assert services.opened_folders == [output_path.parent]
            await pilot.press("down", "x")
            assert second.cancelled

    asyncio.run(exercise())
