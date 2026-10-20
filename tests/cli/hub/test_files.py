# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Files section and its background jobs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from textual.widgets import Input

from stenographer.cli.hub.app import HubApp
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
            assert str(tmp_path) in text
            assert "alpha.wav" in text and "00:02" in text
            assert "beta.wav" in text and "00:03" in text

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
            assert "[Speaker 1]" in text and "fixture line" in text

            output_path = tmp_path / "exports" / "alpha.md"
            first.state = "completed"
            first.output_path = output_path
            await pilot.press("e")
            assert services.opened_folders == [output_path.parent]
            await pilot.press("down", "x")
            assert second.cancelled

    asyncio.run(exercise())
