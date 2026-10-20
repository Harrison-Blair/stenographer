# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless Textual tests for live controls and transcript updates."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from textual.widgets import Select, Static

from stenographer.cli.live.app import LiveApp
from stenographer.lib.live.transcript_line import TranscriptLine


class FakeSession:
    def __init__(self):
        self.paused = False
        self.path = Path("saved-live-session")
        self.lines = []
        self.speakers = (("speaker-1", "Speaker 1"),)
        self.source_states = {"mic": "on", "system": "on"}
        self.source_reasons = {"mic": None, "system": None}
        self.levels_dbfs = {"mic": -20.0, "system": -30.0}
        self.meter_floor_dbfs = -70.0
        self.failed_phrase_count = 0
        self.elapsed_seconds = 3.0
        self.queue_depth = 2
        self.model_name = "test-model"
        self.callbacks = []
        self.actions = []
        self.emit_during_stop = False
        self.stop_callback_blocked = False

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def start(self):
        self.actions.append("start")

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
        self.speakers = ((speaker_id, name),)
        self.lines = [
            replace(line, label=name) if line.speaker_id == speaker_id else line
            for line in self.lines
        ]

    def stop(self):
        self.actions.append("stop")
        if self.emit_during_stop:
            line = TranscriptLine(1.0, 2.0, "wall", "mic", "you", "You", "words")
            callback_thread = threading.Thread(target=self.callbacks[0], args=(line,), daemon=True)
            callback_thread.start()
            callback_thread.join(timeout=0.1)
            self.stop_callback_blocked = callback_thread.is_alive()

    def emit(self, line):
        self.lines.append(line)
        callback_thread = threading.Thread(
            target=lambda: [callback(line) for callback in self.callbacks], daemon=True
        )
        callback_thread.start()


def test_pilot_controls_show_lines_rename_old_lines_and_stop():
    async def exercise():
        session = FakeSession()
        app = LiveApp(session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "start" in session.actions
            status = str(app.query_one("#status", Static).render())
            assert "REC 00:00:03" in status
            assert "m ON" in status and "s ON" in status
            assert "test-model" in status and "queue 2" in status

            await pilot.press("space")
            await pilot.press("m")
            await pilot.press("s")
            assert "pause" in session.actions
            assert ("toggle", "mic") in session.actions
            assert ("toggle", "system") in session.actions

            line = TranscriptLine(
                3661.0,
                3662.0,
                "wall",
                "system",
                "speaker-1",
                "Speaker 1",
                "recognized words",
            )
            session.emit(line)
            await pilot.pause()
            transcript = str(app.query_one("#transcript", Static).render())
            assert "01:01:01  Speaker 1  recognized words" in transcript

            await pilot.press("r")
            await pilot.pause()
            app.screen.query_one("#speaker-select", Select).value = "speaker-1"
            app.screen.query_one("#speaker-name").value = "Alice"
            await pilot.click("#rename-submit")
            await pilot.pause()
            transcript = str(app.query_one("#transcript", Static).render())
            assert ("rename", "speaker-1", "Alice") in session.actions
            assert "01:01:01  Alice  recognized words" in transcript

            await pilot.press("q")
            assert session.actions[-1] == "stop"

    import asyncio

    asyncio.run(exercise())


def test_meter_maps_quiet_levels_between_the_configured_floor_and_top():
    cases = {
        -80.0: "·····",
        -70.0: "·····",
        -50.0: "█····",
        -40.0: "██···",
        -20.0: "████·",
        -10.0: "█████",
        float("-inf"): "·····",
    }

    for level, expected in cases.items():
        assert LiveApp._format_meter(level, -70.0) == expected


def test_pilot_refreshes_meter_from_the_latest_block_level():
    async def exercise():
        session = FakeSession()
        session.levels_dbfs = {"mic": -80.0, "system": -80.0}
        app = LiveApp(session)
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one("#status", Static).render())
            assert "m ON [····· -80 dBFS]" in status

            session.levels_dbfs["mic"] = -50.0
            await pilot.pause(0.2)
            status = str(app.query_one("#status", Static).render())
            assert "m ON [█···· -50 dBFS]" in status

    import asyncio

    asyncio.run(exercise())


def test_status_shows_the_failed_phrase_count():
    async def exercise():
        session = FakeSession()
        session.failed_phrase_count = 2
        app = LiveApp(session)
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one("#status", Static).render())
            assert "failed phrases 2" in status

    import asyncio

    asyncio.run(exercise())


def test_stop_does_not_block_the_ui_while_transcript_callbacks_finish():
    async def exercise():
        session = FakeSession()
        session.emit_during_stop = True
        app = LiveApp(session)
        async with app.run_test() as pilot:
            await pilot.press("q")
            assert not session.stop_callback_blocked

    import asyncio

    asyncio.run(exercise())


def test_ctrl_c_stops_and_saves_the_session():
    async def exercise():
        session = FakeSession()
        app = LiveApp(session)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            assert session.actions[-1] == "stop"

    import asyncio

    asyncio.run(exercise())
