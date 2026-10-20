# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for live panels and transcript views in the hub."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from textual.widgets import Input, Select, Static

from stenographer.cli.hub.app import HubApp
from stenographer.lib.live.transcript_line import TranscriptLine


class FakeSession:
    def __init__(self):
        self.paused = False
        self.path = Path("saved-live-session")
        self.lines = [
            TranscriptLine(2.0, 2.5, "wall", "system", "speaker-2", "Speaker 2", "system words"),
            TranscriptLine(1.0, 1.5, "wall", "mic", "you", "You", "mic words"),
        ]
        self.speakers = (("speaker-1", "Speaker 1"), ("speaker-2", "Speaker 2"))
        self.source_states = {"mic": "on", "system": "on"}
        self.source_reasons = {"mic": None, "system": None}
        self.levels_dbfs = {"mic": -20.0, "system": -30.0}
        self.meter_floor_dbfs = -70.0
        self.failed_phrase_count = 1
        self.elapsed_seconds = 3.0
        self.queue_depth = 2
        self.model_name = "test-model"
        self.actions = []

    def toggle(self, source):
        self.actions.append(("toggle", source))
        self.source_states[source] = "off" if self.source_states[source] == "on" else "on"

    def pause(self):
        self.actions.append("pause")
        self.paused = True

    def resume(self):
        self.actions.append("resume")
        self.paused = False

    def rename(self, speaker_id, name):
        self.actions.append(("rename", speaker_id, name))
        self.speakers = tuple(
            (current_id, name if current_id == speaker_id else label)
            for current_id, label in self.speakers
        )
        self.lines = [
            replace(line, label=name) if line.speaker_id == speaker_id else line
            for line in self.lines
        ]


class FakeServices:
    def __init__(self):
        self.session = FakeSession()
        self.recording = True
        self.files_running = False
        self.actions = []

    def start_recording(self):
        self.actions.append("start-recording")
        self.recording = True

    def stop_recording(self):
        self.actions.append("stop-recording")
        self.recording = False
        self.session = None

    def cancel_files(self):
        self.actions.append("cancel-files")
        self.files_running = False


def test_pilot_live_mixed_and_split_views_keep_time_order():
    async def exercise():
        app = HubApp(FakeServices())
        async with app.run_test() as pilot:
            await pilot.pause()
            content = str(app.query_one("#section-content", Static).render())
            assert "transcript · mixed · 2 speakers" in content
            assert "[Speaker 2]  system words" in content
            assert "[You]  mic words" in content
            assert "model test-model" in content
            assert "queue 2 · failed 1 · CPU " in content
            assert "REC · 00:00:03" in content
            assert "Default output monitor" in content
            assert "dBFS" in content

            await pilot.press("v")
            split = str(app.query_one("#section-content", Static).render())
            assert "transcript · split · 2 speakers" in split
            rows = [
                row for row in split.splitlines() if "mic words" in row or "system words" in row
            ]
            assert len(rows) == 2
            assert rows[0].startswith("00:00:01") and rows[1].startswith("00:00:02")
            assert "mic words" in rows[0] and "system words" not in rows[0]
            assert "system words" in rows[1] and "mic words" not in rows[1]

    asyncio.run(exercise())


def test_pilot_live_renames_a_speaker_and_updates_existing_lines():
    async def exercise():
        services = FakeServices()
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("r")
            app.screen.query_one("#speaker-select", Select).value = "speaker-2"
            app.screen.query_one("#speaker-name", Input).value = "Alice"
            await pilot.click("#rename-submit")
            await pilot.pause()

            content = str(app.query_one("#section-content", Static).render())
            assert ("rename", "speaker-2", "Alice") in services.session.actions
            assert "[Alice]  system words" in content

    asyncio.run(exercise())


def test_pilot_live_keys_toggle_sources_and_pause_resume():
    async def exercise():
        services = FakeServices()
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.press("s")
            await pilot.press("space")
            await pilot.press("space")

        assert services.session.actions == [
            ("toggle", "mic"),
            ("toggle", "system"),
            "pause",
            "resume",
        ]

    asyncio.run(exercise())
