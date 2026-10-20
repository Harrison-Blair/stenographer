# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for live panels and transcript views in the hub."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from rich.color import Color
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


def _screen_text(app: HubApp) -> str:
    return "\n".join(
        "".join(segment.text for segment in strip._segments)
        for strip in app.screen._compositor.render_strips()
    )


def test_pilot_live_has_board_panels_and_captioned_split_columns():
    async def exercise():
        services = FakeServices()
        services.recording = False
        services.session = None
        app = HubApp(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            rec = app.query_one("#live-rec", Static)
            mic = app.query_one("#live-mic", Static)
            system = app.query_one("#live-system", Static)
            transcript = app.query_one("#live-transcript", Static)
            top = (rec, mic, system)
            assert all(panel.styles.border.top[0] == "round" for panel in (*top, transcript))
            assert len({panel.region.y for panel in top}) == 1
            assert rec.region.x < mic.region.x < system.region.x
            assert transcript.region.y > rec.region.y
            assert "00:00:00" in _screen_text(app)

            app.services.session = FakeSession()
            app.services.recording = True
            app._refresh_view()
            await pilot.pause()
            mixed = _screen_text(app)
            assert "transcript · mixed · 2 speakers" in mixed
            assert "00:00:03" in mixed
            time_segments = [
                segment
                for strip in app.screen._compositor.render_strips()
                for segment in strip._segments
                if segment.text.strip() == "00:00:03"
            ]
            assert len(time_segments) == 1 and time_segments[0].style.bold
            assert "[m] MIC" in mixed and "Default input" in mixed
            assert "[s] SYSTEM" in mixed and "Default output" in mixed
            assert "-20 dBFS" in mixed and "-30 dBFS" in mixed
            assert "▁" in mixed
            assert "You" in mixed and "mic words" in mixed
            assert "Speaker 2" in mixed and "system words" in mixed
            you_segments = [
                segment
                for strip in app.screen._compositor.render_strips()
                for segment in strip._segments
                if segment.text.strip() == "You"
            ]
            assert len(you_segments) == 1
            you_style = you_segments[0].style
            assert you_style.bold
            assert you_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
            assert you_style.bgcolor is None or you_style.bgcolor.is_default
            assert not app.query_one("#section-content", Static).display
            assert "1-6 sections" in mixed

            await pilot.press("v")
            split = _screen_text(app)
            assert "MIC · what you said" in split
            assert "SYSTEM · everyone else" in split
            assert "00:00:01" in split and "00:00:02" in split
            split_rows = [row for row in split.splitlines() if "You" in row or "Speaker 2" in row]
            assert len(split_rows) == 2
            assert all("·" in row for row in split_rows)

    asyncio.run(exercise())


def test_sidebar_card_is_section_owned_and_live_shows_engine_status():
    async def exercise():
        app = HubApp(FakeServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            card = app.query_one("#sidebar-card", Static)
            sidebar = app.query_one("#sidebar", Static)
            assert card.region.y > sidebar.region.y
            assert card.styles.border.top[0] == "round"
            assert "engine" in str(card.render())
            assert "test-model" in str(card.render())
            assert "queue 2" in str(card.render())
            app.set_sidebar_card("Files queue · 3", section="files")
            await pilot.press("2")
            assert "Files queue · 3" in str(card.render())
            await pilot.press("1")
            assert "test-model" in str(card.render())

    asyncio.run(exercise())


def test_pilot_live_mixed_and_split_views_keep_time_order():
    async def exercise():
        app = HubApp(FakeServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            content = _screen_text(app)
            assert "transcript · mixed · 2 speakers" in content
            assert "Speaker 2" in content and "system words" in content
            assert "You" in content and "mic words" in content
            card = str(app.query_one("#sidebar-card", Static).render())
            assert "test-model" in card
            assert "queue 2 · failed 1" in card
            assert "00:00:03" in content
            assert "Default output" in content and "monitor" in content
            assert "dBFS" in content

            await pilot.press("v")
            split = _screen_text(app)
            assert "transcript · split · 2 speakers" in split
            assert "MIC · what you said" in split
            assert "SYSTEM · everyone else" in split
            rows = [
                row for row in split.splitlines() if "mic words" in row or "system words" in row
            ]
            assert len(rows) == 2
            assert "00:00:01" in rows[0] and "00:00:02" in rows[1]
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

            content = _screen_text(app)
            assert ("rename", "speaker-2", "Alice") in services.session.actions
            assert "Alice" in content and "system words" in content

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
