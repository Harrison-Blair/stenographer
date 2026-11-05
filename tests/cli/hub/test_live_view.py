# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for live panels and transcript views in the hub."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rich.color import Color
from textual.events import MouseScrollDown
from textual.widget import Widget
from textual.widgets import Input, Select, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.widgets.clock import Clock
from stenographer.lib.live.transcript_line import TranscriptLine
from tests.cli.hub.support import _has_split_header, _screen_text, make_app


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
        self.levels_dbfs = {"mic": -20.0, "system": -30.0}
        self.meter_floor_dbfs = -70.0
        self.failed_phrase_count = 1
        self.elapsed_seconds = 3.0
        self.queue_depth = 2
        self.relabel_progress = None
        self.idle_unload_deadline = None
        self.model_name = "medium.en"
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


async def test_pilot_live_has_board_panels_and_captioned_split_columns(tmp_path):
    services = FakeServices()
    services.recording = False
    services.session = None
    app = make_app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        rec = app.screen.query_one("#rec-panel", Widget)
        mic = app.screen.query_one("#mic-meter", Widget)
        system = app.screen.query_one("#system-meter", Widget)
        transcript = app.screen.query_one("#transcript-frame", Widget)
        top = (rec, mic, system)
        assert all(panel.styles.border.top[0] == "round" for panel in (*top, transcript))
        assert len({panel.region.y for panel in top}) == 1
        assert rec.region.x < mic.region.x < system.region.x
        assert transcript.region.y > rec.region.y
        assert app.screen.query_one("#rec-clock", Clock).value == "00:00:00"

        app.services.session = FakeSession()
        app.services.recording = True
        app.refresh_view()
        await pilot.pause()
        mixed = _screen_text(app)
        assert "transcript · 2 speakers" in mixed
        assert app.screen.query_one("#rec-clock", Clock).value == "00:00:03"
        assert "[m] MIC" in mixed and "Default input" in mixed
        assert "[s] SYSTEM" in mixed and "default output" in mixed
        assert mixed.count("-inf dBFS  peak -inf") == 2
        assert "100  200  400  800 1k6 3k2 6k4" in mixed
        assert "You" in mixed and "mic words" in mixed
        assert "Speaker 2" in mixed and "system words" in mixed
        you_segments = [
            segment
            for strip in app.screen._compositor.render_strips()
            for segment in strip._segments
            if segment.text.strip() == "You"
        ]
        # One in the transcript and one in the speaker bar.
        assert len(you_segments) == 2
        for you_segment in you_segments:
            you_style = you_segment.style
            assert you_style.bold
            assert you_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
            assert you_style.bgcolor is None or you_style.bgcolor.is_default
        assert not app.screen.query_one("#section-content", Static).display
        assert "? help · q quit" in mixed

        await pilot.press("v")
        split = _screen_text(app)
        assert _has_split_header(split)
        assert "00:00:01" in split and "00:00:02" in split
        split_rows = [
            row for row in split.splitlines() if "mic words" in row or "system words" in row
        ]
        assert len(split_rows) == 2
        assert all("·" in row for row in split_rows)


async def test_speaker_bar_sits_above_the_transcript_and_engine_status_stays(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        bar = app.screen.query_one("#speaker-bar", Static)
        assert bar.region.y < app.screen.query_one("#transcript").region.y
        assert bar.region.width == app.screen.query_one("#transcript").region.width
        items = str(bar.render()).split("   ")
        assert items[0].startswith("You ")
        assert [item.rsplit(" ", 1)[0] for item in items[:2]] == ["You", "Speaker 2"]
        assert items[-1] == "! 1 phrase failed"
        for key in "21":
            await pilot.press(key)
            engine = str(app.screen.query_one("#top-engine", Static).render())
            assert engine.startswith("bark-pro-int8 ")


async def test_pilot_live_mixed_and_split_views_keep_time_order(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        content = _screen_text(app)
        assert "transcript · 2 speakers" in content
        assert "Speaker 2" in content and "system words" in content
        assert "You" in content and "mic words" in content
        bar = str(app.screen.query_one("#speaker-bar", Static).render())
        assert "! 1 phrase failed" in bar
        assert app.screen.query_one("#rec-clock", Clock).value == "00:00:03"
        assert "default output" in content
        assert "dBFS" in content

        await pilot.press("v")
        split = _screen_text(app)
        assert "mixed  ▶ split" in split
        assert _has_split_header(split)
        rows = [row for row in split.splitlines() if "mic words" in row or "system words" in row]
        assert len(rows) == 2
        assert "00:00:01" in rows[0] and "00:00:02" in rows[1]
        assert "mic words" in rows[0] and "system words" not in rows[0]
        assert "system words" in rows[1] and "mic words" not in rows[1]


async def test_pilot_live_renames_a_speaker_and_updates_existing_lines(tmp_path):
    services = FakeServices()
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press("r")
        app.screen.query_one("#speaker-select", Select).value = "speaker-2"
        app.screen.query_one("#speaker-name", Input).value = "Alice"
        await pilot.click("#dialog-rename")
        await pilot.pause()

        content = _screen_text(app)
        assert ("rename", "speaker-2", "Alice") in services.session.actions
        assert "Alice" in content and "system words" in content


async def test_pilot_live_lists_and_renames_room_speakers(tmp_path):
    services = FakeServices()
    session = services.session
    session.lines = [
        TranscriptLine(1.0, 1.5, "wall", "mic", "room-1", "Room 1", "first room words"),
        TranscriptLine(2.0, 2.5, "wall", "mic", "room-2", "Room 2", "second room words"),
    ]
    session.speakers = (("room-1", "Room 1"), ("room-2", "Room 2"))
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        content = _screen_text(app)
        assert "Room 1" in content and "Room 2" in content
        await pilot.press("r")
        select = app.screen.query_one("#speaker-select", Select)
        listed = [speaker_id for speaker_id, _label in app.screen._speakers]
        assert listed == ["room-1", "room-2"]
        await pilot.pause()
        dialog_text = _screen_text(app)
        assert "Rename speaker" in dialog_text
        assert "system speaker" not in dialog_text
        select.value = "room-2"
        app.screen.query_one("#speaker-name", Input).value = "Dana"
        await pilot.click("#dialog-rename")
        await pilot.pause()

        content = _screen_text(app)
        assert ("rename", "room-2", "Dana") in session.actions
        assert "Dana" in content and "Room 1" in content


def _visible_segment(app: HubApp, text: str):
    for strip in app.screen._compositor.render_strips():
        for segment in strip._segments:
            if text in segment.text:
                return segment
    raise AssertionError(f"{text!r} is not visible")


async def test_live_rec_panel_shows_only_the_inline_rec_label(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        rec = app.screen.query_one("#rec-panel", Widget)
        assert not rec.border_title
        assert _screen_text(app).count("REC") == 1


async def test_record_footer_matches_the_board_hint_row(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        hints = app.screen.query_one("#key-hints", Static).render().plain
        assert hints == (
            "? help · q quit · enter stop & save · space pause · m mic · s system"
            " · v view · r rename"
        )


async def test_live_elapsed_uses_digits_widget(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        elapsed = app.screen.query_one("#rec-clock", Clock)
        assert elapsed.value == "00:00:03"
        assert elapsed.region.height == 3


async def test_live_speaker_colors_are_distinct_stable_and_used_in_rename_choices(tmp_path):
    app = make_app(tmp_path, FakeServices())
    session = app.services.session
    session.lines.extend(
        (
            TranscriptLine(0.5, 0.8, "wall", "system", "speaker-1", "Speaker 1", "first words"),
            TranscriptLine(3.0, 3.5, "wall", "system", "speaker-3", "Speaker 3", "third words"),
        )
    )
    session.speakers = (
        ("speaker-1", "Speaker 1"),
        ("speaker-2", "Speaker 2"),
        ("speaker-3", "Speaker 3"),
    )
    expected_colors = {
        "You": "#5fd7ff",
        "Speaker 1": "#ffaf5f",
        "Speaker 2": "#d787ff",
        "Speaker 3": "#87d787",
    }
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        mixed_styles = {}
        for label, color in expected_colors.items():
            segment = _visible_segment(app, label)
            assert segment.style.bold
            assert segment.style.color == Color.parse(color)
            assert segment.style.bgcolor is None or segment.style.bgcolor.is_default
            mixed_styles[label] = segment.style.color

        await pilot.press("v")
        await pilot.pause()
        for label, color in expected_colors.items():
            segment = _visible_segment(app, label)
            assert segment.style.bold
            assert segment.style.color == Color.parse(color)
            assert segment.style.color == mixed_styles[label]
            assert segment.style.bgcolor is None or segment.style.bgcolor.is_default

        app.push_screen(RenameDialog(session.speakers))
        await pilot.pause()
        select = app.screen.query_one("#speaker-select", Select)
        select.focus()
        await pilot.press("enter")
        await pilot.pause()
        for label, color in list(expected_colors.items())[1:]:
            segment = _visible_segment(app, label)
            assert segment.style.bold
            assert segment.style.color == Color.parse(color)
            assert segment.style.bgcolor is None or segment.style.bgcolor.is_default


async def test_live_key_hints_style_keys_and_descriptions_without_fills(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        hints = app.screen.query_one("#transcript-hints", Static).render().plain
        assert hints == "↑↓ line · PgUp/Dn page · End follow"
        footer = app.screen._compositor.render_strips()[-1]._segments
        key = next(segment for segment in footer if "space" in segment.text)
        description = next(segment for segment in footer if "pause" in segment.text)
        assert key.style.bold
        assert key.style.color == Color.parse("#5fd7ff")
        assert key.style.bgcolor is None or key.style.bgcolor.is_default
        assert description.style.color is None or description.style.color.is_default
        assert description.style.bgcolor is None or description.style.bgcolor.is_default


async def test_live_transcript_scrolls_in_mixed_and_split_views_and_follows_new_lines(tmp_path):
    services = FakeServices()
    session = services.session
    session.lines = [
        TranscriptLine(float(index), float(index + 1), "wall", "mic", "you", "You", f"line {index}")
        for index in range(40)
    ]
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scroll = app.screen.query_one("#transcript")
        assert scroll.max_scroll_y > 0
        assert scroll.scroll_y == scroll.max_scroll_y

        await pilot.press("home")
        await pilot.press("pagedown")
        page_position = scroll.scroll_y
        assert page_position > 1
        await pilot.press("pageup")
        assert scroll.scroll_y < page_position
        await pilot._post_mouse_events([MouseScrollDown], widget=scroll)
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("home")
        await pilot.press("down")
        assert scroll.scroll_y == 1
        held_position = scroll.scroll_y
        await pilot.pause(0.25)
        assert scroll.scroll_y == held_position
        session.lines.append(TranscriptLine(40.0, 41.0, "wall", "mic", "you", "You", "new line"))
        app.refresh_view()
        await pilot.pause()
        assert scroll.scroll_y == held_position

        await pilot.press("end")
        await pilot.press("v")
        assert scroll.scroll_y == scroll.max_scroll_y
        await pilot.press("home")
        await pilot.press("down")
        assert scroll.scroll_y == 1
        await pilot.press("end")
        session.lines.append(
            TranscriptLine(41.0, 42.0, "wall", "system", "speaker-2", "Speaker 2", "latest line")
        )
        app.refresh_view()
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        assert "mixed  ▶ split" in _screen_text(app)


async def test_live_transcript_title_is_legible(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        transcript_title = _visible_segment(app, "transcript · 2 speakers")
        assert transcript_title.style.bold
        assert transcript_title.style.color is None or transcript_title.style.color.is_default


async def test_system_source_state_and_device_fit_on_one_line(tmp_path):
    app = make_app(tmp_path, FakeServices())
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.pause()
        system_lines = [row for row in _screen_text(app).splitlines() if "[s] SYSTEM" in row]
        assert len(system_lines) == 1
        assert "on · default output" in system_lines[0]
        assert "○ quiet" in system_lines[0]
