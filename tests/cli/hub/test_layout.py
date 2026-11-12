# SPDX-License-Identifier: GPL-3.0-or-later
"""The hub layout: full-width transcripts, speaker bar, stacked Library and top summaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from rich.text import Text
from textual.app import App
from textual.widgets import Input, Select, Static

from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.engine_status import EngineStatus
from stenographer.cli.hub.widgets.speaker_bar import SpeakerBar
from stenographer.cli.hub.widgets.spectrum_meter_model import SpectrumMeterModel
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from tests.cli.hub.support import (
    _fields,
    _layout_problems,
    _screen_text,
    _speaker_bar,
    make_app,
)
from tests.cli.hub.test_checks_tab import _board_report
from tests.cli.hub.test_library import FakeJob
from tests.cli.hub.test_library import FakeServices as LibraryServices
from tests.cli.hub.test_record_screen import _app, _services, _until
from tests.cli.hub.test_shell import FakeSampler

SIZES = ((150, 45), (120, 35))
TEXT = "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima"
ROOM_LINES = [
    TranscriptLine(
        i * 6.0, i * 6.0 + 5, "", "mic", f"room-{i % 12 + 1}", f"Room {i % 12 + 1}", TEXT
    )
    for i in range(24)
]


def _write_sessions(tmp_path, count):
    for index in range(count):
        writer = SessionWriter.open(
            tmp_path, datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=index)
        )
        for line in ROOM_LINES:
            writer.append_line(line)
        writer.close()


def _selected_rows(app) -> list[str]:
    return [row for row in _screen_text(app).splitlines() if "▶" in row and " rec " in row]


def _rows_text(library) -> str:
    return library.query_one("#library-list", Static).render().plain


async def _record_with_rooms(pilot, services, created, app):
    await pilot.pause()
    await pilot.press("space")
    await _until(pilot, lambda: services.recording)
    session = created[0]
    session.lines = list(ROOM_LINES)
    session.speakers = tuple(dict.fromkeys((line.speaker_id, line.label) for line in ROOM_LINES))
    app.refresh_view()
    await pilot.pause()
    return session


async def _open_library(pilot, app, count):
    await pilot.press("2")
    await _until(pilot, lambda: app.library_screen.entry_count == count)
    await _until(pilot, lambda: app.library_screen.detail is not None)
    app.refresh_view()
    await pilot.pause()


def test_speaker_bar_starts_a_new_row_only_between_items():
    bar = SpeakerBar()
    bar.items = (Text("Speaker 10 0:15"), Text("Speaker 11 0:15"), Text("! 2 phrases failed"))

    assert bar.bar_text(40).plain == "Speaker 10 0:15   Speaker 11 0:15\n! 2 phrases failed"
    assert bar.bar_text(15).plain == "Speaker 10 0:15\nSpeaker 11 0:15\n! 2 phrases failed"
    assert bar.bar_text(70).plain == "Speaker 10 0:15   Speaker 11 0:15   ! 2 phrases failed"


async def test_record_transcript_takes_the_full_width(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await _record_with_rooms(pilot, services, created, app)
        assert app.screen.query_one("#transcript-scroll-content").size.width >= 140
        created[0].release.set()


async def test_library_transcript_takes_the_full_width_and_list_sits_above_it(tmp_path):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 1)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await _open_library(pilot, app, 1)
        assert app.screen.query_one("#transcript-scroll-content").size.width >= 140
        listing = app.screen.query_one("#library-list-frame").region
        assert listing.bottom <= app.screen.query_one("#library-transcript").region.y


async def test_record_bar_wraps_twelve_speakers_and_keeps_warnings_last(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        session.failed_phrase_count = 2
        session.audio_failed_sources = ("mic",)
        app.refresh_view()
        await pilot.pause()
        bar = app.screen.query_one("#speaker-bar", Static)
        assert bar.size.height == 3, "each talk time takes its 5-cell slot"
        rows = str(bar.render()).splitlines()
        assert rows[0].startswith("Room 1  0:")
        assert "   ".join(rows).endswith("! 2 phrases failed   ! mic audio not saved")
        for number in range(1, 13):
            assert f"Room {number}  0:" in "\n".join(rows), "label and time stay on one row"
        assert bar.region.bottom <= app.screen.query_one("#transcript").region.y
        session.release.set()


async def test_speaker_bar_flows_its_items_again_when_its_width_changes():
    class BarApp(App):
        def compose(self):
            yield SpeakerBar()

    app = BarApp()
    async with app.run_test(size=(60, 10)) as pilot:
        bar = app.query_one(SpeakerBar)
        await pilot.pause()
        bar.set_items((Text("Speaker 10 0:15"), Text("Speaker 11 0:15")))
        await pilot.pause()
        assert str(bar.render()) == "Speaker 10 0:15   Speaker 11 0:15"
        await pilot.resize_terminal(25, 10)
        await pilot.pause()
        assert str(bar.render()) == "Speaker 10 0:15\nSpeaker 11 0:15"


async def test_record_bar_leaves_out_a_speaker_with_no_lines(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        session.speakers = (*session.speakers, ("room-99", "Room 99"))
        session.lines.append(ROOM_LINES[0])
        app.refresh_view()
        await pilot.pause()
        assert "Room 99" not in _screen_text(app)
        assert "transcript ·  12 speakers" in _screen_text(app)
        session.release.set()


async def test_saved_record_bar_leaves_out_a_speaker_with_no_lines(tmp_path):
    """A saved session can still list a speaker that has no lines."""
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        session.speakers = (*session.speakers, ("room-99", "Room 99"))
        session.lines.append(ROOM_LINES[0])
        await pilot.press("enter")
        await _until(pilot, session.stop_entered.is_set)
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        app.refresh_view()
        await pilot.pause()
        assert app.record_screen.record_state() == "saved"
        assert "Room 99" not in _speaker_bar(app)
        assert "transcript ·  12 speakers" in _screen_text(app)


@pytest.mark.parametrize(
    "error", [OSError("no space left on device"), RuntimeError("the session writer is closed")]
)
async def test_failed_live_rename_shows_a_notice_and_the_hub_stays_open(tmp_path, error):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)

        def rename(_speaker_id, _name):
            raise error

        session.rename = rename
        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one("#speaker-select", Select).value = "room-2"
        app.screen.query_one("#speaker-name", Input).value = "Ann"
        await pilot.click("#dialog-rename")
        await pilot.pause()
        assert app.is_running
        assert str(error) in "\n".join(str(notice.message) for notice in app._notifications)
        session.release.set()


async def test_saved_record_rename_changes_one_of_two_speakers_that_share_a_name(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        session.lines = [
            TranscriptLine(0.0, 1.0, "", "mic", "room-1", "Dana", TEXT),
            TranscriptLine(1.0, 2.0, "", "mic", "room-2", "Dana", TEXT),
        ]
        await pilot.press("enter")
        await _until(pilot, session.stop_entered.is_set)
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        await _until(pilot, lambda: not app.is_busy(session.path.name))
        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one("#speaker-select", Select).value = "room-1"
        app.screen.query_one("#speaker-name", Input).value = "Diana"
        await pilot.click("#dialog-rename")
        await _until(pilot, lambda: not app.is_busy(session.path.name))
        store = services.session_store
        await _until(pilot, lambda: store.read(session.path.name).revision != "transcript.jsonl")

        labels = {line.speaker_id: line.label for line in store.read(session.path.name).lines}
        assert labels == {"room-1": "Diana", "room-2": "Dana"}


async def test_record_bar_gives_a_room_speaker_the_color_of_its_transcript_row(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        segments = [
            segment
            for strip in app.screen._compositor.render_strips()
            for segment in strip._segments
            if segment.text.strip() == "Room 2"
        ]
        assert len({segment.style.color for segment in segments}) == 1
        assert len(segments) >= 2, "one in the bar and one in the transcript"
        session.release.set()


async def test_library_list_keeps_the_selected_row_in_view(tmp_path):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 12)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await _open_library(pilot, app, 12)
        for _ in range(11):
            await pilot.press("down")
        await pilot.pause()
        assert len(_selected_rows(app)) == 1
        await pilot.press("up")
        await pilot.pause()
        assert len(_selected_rows(app)) == 1


async def test_library_list_keeps_the_wheel_position_while_a_file_job_runs(tmp_path):
    _write_sessions(tmp_path, 30)
    services = LibraryServices(tmp_path / "sessions")
    job = FakeJob("file-1", tmp_path / "source.wav")
    services.jobs.append(job)
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        library = app.library_screen
        await pilot.press("2")
        await _until(pilot, lambda: library.entry_count == 31)
        for _ in range(20):
            await pilot.press("down")
        await pilot.pause(0.05)
        scroll = app.screen.query_one("#library-list-scroll")
        assert scroll.scroll_y > 0
        scroll.scroll_to(y=0, animate=False, immediate=True)
        await pilot.pause()

        job.progress = replace(job.progress, percent=job.progress.percent + 1)
        await _until(pilot, lambda: f"{job.progress.percent}%" in _rows_text(library))
        await pilot.pause(0.05)
        assert scroll.scroll_y == 0

        await pilot.press("down")
        await pilot.pause(0.05)
        assert len(_selected_rows(app)) == 1, "a selection move still brings its row into view"


async def test_library_list_row_click_selects_after_the_list_scrolled(tmp_path):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 12)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await _open_library(pilot, app, 12)
        library = app.library_screen
        for _ in range(11):
            await pilot.press("down")
        await pilot.pause()
        scroll = app.screen.query_one("#library-list-scroll")
        assert scroll.scroll_y == 4
        await pilot.click("#library-list-scroll", offset=(4, 0))
        await pilot.pause()
        assert library.selected_id == library.entries[4].entry_id


async def test_library_rename_changes_every_speaker_with_that_name_in_one_revision(tmp_path):
    speakers = (("room-1", "Dana"), ("room-2", "Dana"), ("room-3", "Eve"))
    writer = SessionWriter.open(tmp_path, datetime(2026, 11, 1, tzinfo=UTC))
    for index, (speaker_id, label) in enumerate(speakers):
        writer.append_line(TranscriptLine(index, index + 1, "", "mic", speaker_id, label, TEXT))
    writer.close()
    services, _created = _services(tmp_path)
    store = services.session_store
    session_id = writer.path.name
    revision_before = store.read(session_id).revision
    files_before = len(list(writer.path.glob("transcript*.jsonl")))
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await _open_library(pilot, app, 1)
        await pilot.press("r")
        await pilot.pause()
        listed = [label for _speaker_id, label in app.screen._speakers]
        assert listed == ["Dana", "Eve"]
        app.screen.query_one("#speaker-select", Select).value = "room-1"
        app.screen.query_one("#speaker-name", Input).value = "Diana"
        await pilot.click("#dialog-rename")
        await _until(pilot, lambda: store.read(session_id).revision != revision_before)
        await _until(pilot, lambda: not app.is_busy(session_id))

    labels = {line.speaker_id: line.label for line in store.read(session_id).lines}
    assert labels == {"room-1": "Diana", "room-2": "Diana", "room-3": "Eve"}
    assert len(list(writer.path.glob("transcript*.jsonl"))) == files_before + 1


@pytest.mark.parametrize("size", SIZES)
async def test_library_search_shows_the_typed_text(tmp_path, size):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 1)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await _open_library(pilot, app, 1)
        await pilot.press("slash", *"zulu")
        await pilot.pause()
        search_row = app.screen.query_one("#library-search-row").region.y
        assert "zulu" in _screen_text(app).splitlines()[search_row]
        assert _layout_problems(app) == []


@pytest.mark.parametrize("size", SIZES)
async def test_transcribe_search_shows_the_typed_text(tmp_path, size):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services, files_home=tmp_path)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await pilot.press("2", "n")
        await pilot.pause()
        await pilot.press("slash", *"zulu")
        await pilot.pause()
        search_row = app.screen.query_one("#transcribe-search").region.y
        assert "zulu" in _screen_text(app).splitlines()[search_row]
        assert app.screen.query_one("#transcribe-search").content_size.height == 1


@pytest.mark.parametrize("size", SIZES)
async def test_vocabulary_add_input_shows_the_typed_text(tmp_path, size):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3", "right", "right")
        await pilot.pause()
        app.config_editor.select("refine.vocabulary")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a", *"zulu")
        await pilot.pause()
        field = app.screen.query_one("#vocab-input")
        assert field.content_size.height == 1
        assert "zulu" in _screen_text(app).splitlines()[field.region.y]


async def _open_library_search(pilot, app):
    await pilot.press("2", "slash")
    return "#library-search"


async def _open_transcribe_search(pilot, app):
    await pilot.press("2", "n")
    await pilot.pause()
    await pilot.press("slash")
    return "#transcribe-search"


async def _open_settings_row(pilot, app):
    await pilot.press("3")
    await pilot.pause()
    app.settings_screen.open_setting("refine.host")
    await pilot.pause()
    await pilot.press("enter")
    return "#config-input"


async def _open_settings_search(pilot, app):
    await pilot.press("3", "slash")
    return "#config-prompt-input"


async def _open_vocabulary_add(pilot, app):
    await pilot.press("3")
    await pilot.pause()
    app.settings_screen.open_setting("refine.vocabulary")
    await pilot.press("enter")
    await pilot.pause()
    await pilot.press("a")
    return "#vocab-input"


async def _open_library_rename(pilot, app):
    await pilot.press("r")
    return "#speaker-name"


async def _open_library_export(pilot, app):
    await pilot.press("x")
    return "#export-folder"


@pytest.mark.parametrize(
    "open_input",
    [
        _open_library_search,
        _open_transcribe_search,
        _open_settings_row,
        _open_settings_search,
        _open_vocabulary_add,
        _open_library_rename,
        _open_library_export,
    ],
)
async def test_every_input_keeps_a_long_value_visible_on_its_text_row(tmp_path, open_input):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 1)
    app = _app(tmp_path, services, files_home=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open_library(pilot, app, 1)
        selector = await open_input(pilot, app)
        await pilot.pause()
        field = app.screen.query_one(selector, Input)
        field.value = "1234567890" * 15
        field.cursor_position = len(field.value)
        await pilot.pause()
        row = _screen_text(app).splitlines()[field.content_region.y]
        assert "7890" in row, row


@pytest.mark.parametrize("size", SIZES)
async def test_library_action_row_keeps_each_busy_word_on_one_row(tmp_path, size):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 1)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await _open_library(pilot, app, 1)
        library = app.library_screen
        app.try_acquire_session(library.selected_id, "test")
        library._rebuild()
        app.refresh_view()
        await pilot.pause()
        assert app.screen.query_one("#library-actions").region.height == 1
        assert _layout_problems(app) == []
        for label in (
            "[r] Rename… · busy",
            "[d] Re-diarize · busy",
            "[t] Re-transcribe · busy",
            "[del] Delete… · busy",
        ):
            assert label in _screen_text(app)

        # A running revision job gives the widest row: delete cancels the job.
        # The job poll saw the busy mark by now, so it does not list the entries again.
        await pilot.pause(0.15)
        job = FakeJob("file-1", tmp_path / "source.wav")
        library.entries = (replace(library.entries[0], job=job),)
        library._draw_detail()
        await pilot.pause()
        assert "[del] Cancel job… · busy" in _screen_text(app)
        assert _layout_problems(app) == []


@pytest.mark.parametrize("size", SIZES)
async def test_no_widget_leaves_its_parent_on_any_screen(tmp_path, size):
    services, created = _services(tmp_path)
    _write_sessions(tmp_path, 9)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert _layout_problems(app) == [], "record idle"
        session = await _record_with_rooms(pilot, services, created, app)
        assert _layout_problems(app) == [], "record recording"
        await pilot.press("enter")
        await _until(pilot, session.stop_entered.is_set)
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "record saved"
        await pilot.press("2")
        await _until(pilot, lambda: app.library_screen.detail is not None)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "library"
        await pilot.press("slash", *"zulu")
        await pilot.pause()
        assert _layout_problems(app) == [], "library search"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert _layout_problems(app) == [], "settings"
        await pilot.press("left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        assert _layout_problems(app) == [], "checks"


async def test_footer_hints_fit_on_every_screen_at_120_columns(tmp_path):
    services, created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()

        def assert_fits(state):
            hints = app.screen.query_one("#key-hints", Static)
            assert len(hints.render().plain) <= hints.content_size.width, state

        for screen in ("record", "library", "settings"):
            app.show_screen(screen)
            await pilot.pause()
            assert_fits(screen)
        await pilot.press("enter")
        await pilot.pause()
        assert_fits("settings row input")
        await pilot.press("escape", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        assert_fits("checks")
        await pilot.press("2", "slash")
        await pilot.pause()
        assert_fits("library search")
        await pilot.press("escape", "1", "space")
        await _until(pilot, lambda: services.recording)
        await pilot.pause()
        assert_fits("record recording")
        await pilot.press("enter")
        session = created[0]
        await _until(pilot, session.stop_entered.is_set)
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        app.refresh_view()
        await pilot.pause()
        assert_fits("record saved")


async def test_settings_rows_show_no_description_and_values_use_the_free_width(tmp_path):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(100, 45)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        # Label, marks and value only: the row ends with its value.
        row = _fields(app)[0]
        assert row.note == ""
        text = _screen_text(app)
        agent_row = next(line for line in text.splitlines() if "Agent key" in line)
        assert agent_row.split("│")[1].split() == ["▶", "Agent", "key", "KEY_RIGHTCTRL"]
        for sentence in ("Agent binding", "Playback volume", "applies to new sessions"):
            assert sentence not in text

        long_value = "alpha-" * 10
        row.set_value(long_value, changed=False)
        await pilot.pause()
        assert long_value in _screen_text(app), "a value without a note stays on one row"


async def test_settings_row_shows_no_note_while_its_input_is_open(tmp_path):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.press("3", "enter")
        await pilot.pause()
        row = next(line for line in _screen_text(app).splitlines() if "Agent key" in line)
        assert "editing" not in row
        assert "enter keeps" not in row
        await pilot.press("escape")
        await pilot.pause()
        row = next(line for line in _screen_text(app).splitlines() if "Agent key" in line)
        assert "editing" not in row


async def test_settings_config_summary_is_the_first_row_of_the_panel(tmp_path):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        summary = app.screen.query_one("#config-summary", Static)
        assert summary.region.y == app.screen.query_one("#config-body").content_region.y
        assert summary.region.y < app.screen.query_one("#config-rows").region.y
        assert str(summary.render()) == "config.toml · 0 unsaved changes   · backups none yet"


# Size tiers (plan "Sizes", "Record", "Checks")

TIER_SIZES = ((150, 45), (120, 35), (100, 30), (80, 24), (60, 16))
TIMES = "\N{MULTIPLICATION SIGN}"


def _region_problems(app, root) -> list[str]:
    """Return the layout problems of the widgets inside ``root`` and of the top and hint rows."""
    roots = (root, app.screen.query_one("#top-bar"), app.screen.query_one("#key-hints"))
    return [
        problem
        for problem in _layout_problems(app)
        if any(
            problem.startswith(f"{node.id} ")
            for top in roots
            for node in (top, *top.query("*"))
            if node.id
        )
    ]


def _assert_one_row(app, selector):
    widget = app.screen.query_one(selector)
    assert widget.region.height == 1, selector
    assert app.screen.region.contains_region(widget.region), selector


def _assert_hints_fit(app, state):
    hints = app.screen.query_one("#key-hints", Static)
    plain = hints.render().plain
    assert len(plain) <= hints.content_size.width, state
    assert "…" not in plain, state
    return plain


@pytest.mark.parametrize("size", TIER_SIZES)
async def test_record_fits_every_tier_in_each_state(tmp_path, size):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert _layout_problems(app) == [], "idle"
        assert _assert_hints_fit(app, "idle").startswith("? help · q quit")
        session = await _record_with_rooms(pilot, services, created, app)
        assert _layout_problems(app) == [], "recording"
        _assert_one_row(app, "#top-bar")
        assert _assert_hints_fit(app, "recording").startswith("? help · q quit · enter")
        frame = app.screen.query_one("#transcript-frame").region
        assert frame.bottom == app.screen.query_one("#key-hints").region.y
        assert app.screen.query_one("#transcript").region.height >= 3, "the transcript shows"
        await pilot.press("space")
        await _until(pilot, lambda: session.paused)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "paused"
        await pilot.press("enter")
        await _until(pilot, session.stop_entered.is_set)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "saving"
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "saved"
        services.failed_stops.append((session, "No space left on device"))
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == [], "failed"


@pytest.mark.parametrize(
    ("size", "parts"),
    [
        ((100, 30), ("● REC", "00:12:08", "started", "[enter] ■ Stop & save", "[space] Ⅱ Pause")),
        ((60, 16), ("● REC", "00:12:08", "[enter] ■ Stop", "[space] Ⅱ Pause")),
    ],
)
async def test_record_panel_is_one_status_line_below_the_wide_tier(tmp_path, size, parts):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        _assert_one_row(app, "#rec-panel")
        row = _screen_text(app).splitlines()[app.screen.query_one("#rec-panel").region.y]
        assert row.startswith(" ● REC "), row
        positions = [row.index(part) for part in parts]
        assert positions == sorted(positions), row
        session.release.set()


async def test_record_meters_shrink_in_three_steps(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        meter = app.screen.query_one("#mic-meter")
        assert meter.content_size.height == 11, "full spectrum"
        assert "1k6" in _screen_text(app)
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert 2 <= meter.content_size.height < 11, "short spectrum"
        assert "1k6" not in _screen_text(app)
        await pilot.resize_terminal(60, 16)
        await pilot.pause()
        assert meter.region.height == 1, "one level line"
        rows = _screen_text(app).splitlines()
        assert rows[meter.region.y].strip().startswith("[m] MIC")
        assert rows[app.screen.query_one("#system-meter").region.y].strip().startswith("[s] SYS")
        session.release.set()


async def test_below_floor_shows_the_size_line_and_the_recording_continues(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        await pilot.resize_terminal(59, 15)
        await pilot.pause()
        lines = [row.strip() for row in _screen_text(app).splitlines() if row.strip()]
        assert lines == [f"60{TIMES}16 needed · now  59{TIMES}15"]
        session.elapsed_seconds += 2
        await pilot.pause(0.2)
        assert services.recording
        await pilot.resize_terminal(70, 15)
        await pilot.pause()
        assert [row.strip() for row in _screen_text(app).splitlines() if row.strip()] == [
            f"60{TIMES}16 needed · now  70{TIMES}15"
        ]
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.2)
        assert "● 00:12:10" in _screen_text(app).splitlines()[0]
        assert _layout_problems(app) == []
        session.release.set()


@pytest.mark.parametrize(
    ("size", "shown", "hidden"),
    [
        ((150, 45), ("bark-pro-int8", "ready", "cpu", "ram"), ()),
        ((100, 30), ("ready", "cpu", "ram"), ("bark-pro-int8",)),
        ((80, 24), ("ready",), ("bark-pro-int8", "cpu", "ram")),
        ((60, 16), ("ready",), ("bark-pro-int8", "cpu", "ram", "00:12:08")),
    ],
)
async def test_top_line_drops_model_then_ram_then_cpu(tmp_path, size, shown, hidden):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        session.queue_depth = 3
        app.refresh_view()
        await pilot.pause()
        _assert_one_row(app, "#top-bar")
        top = _screen_text(app).splitlines()[0]
        for value in ("1 Record", "2 Library", "3 Settings", "●", *shown):
            assert value in top, top
        for value in (*hidden, " all ", "queued"):
            assert value not in top, top
        session.release.set()


def test_hint_row_drops_whole_items_from_the_right_and_keeps_help():
    from stenographer.cli.hub.widgets.key_hints import KeyHints

    hints = KeyHints()
    items = (("?", "help"), ("q", "quit"), ("enter", "stop & save"), ("space", "pause"))
    assert hints.fitting(items, 100) == items
    assert hints.fitting(items, 40) == items[:3]
    assert hints.fitting(items, 15) == items[:2]
    assert hints.fitting(items, 14) == items[:1]
    assert hints.fitting(items, 3) == items[:1]


async def test_hint_row_hides_help_and_quit_while_an_input_has_focus_at_60(tmp_path):
    services, _created = _services(tmp_path)
    _write_sessions(tmp_path, 1)
    app = _app(tmp_path, services)
    async with app.run_test(size=(60, 16)) as pilot:
        await _open_library(pilot, app, 1)
        assert _assert_hints_fit(app, "library").startswith("? help · q quit")
        await pilot.press("slash")
        await pilot.pause()
        plain = _assert_hints_fit(app, "search")
        assert "help" not in plain
        assert "quit" not in plain


@pytest.mark.parametrize("size", TIER_SIZES)
async def test_checks_fit_every_tier(tmp_path, size):
    services, _created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        assert _region_problems(app, app.checks_tab) == []
        _assert_one_row(app, "#top-bar")
        _assert_hints_fit(app, "checks")
        for _ in range(7):
            await pilot.press("down")
            await pilot.pause()
            row = app.checks_tab.index
            selected = [line for line in _screen_text(app).splitlines() if "▶ " in line]
            label = report.checks[row].label
            assert any(label in line for line in selected), f"selected row {label} shows"
        if size[0] < 80:
            await pilot.press("enter")
            await pilot.pause()
            assert _region_problems(app, app.checks_tab) == []


async def test_checks_narrow_tier_opens_the_detail_with_enter_and_returns_with_escape(tmp_path):
    services, _created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        detail = app.screen.query_one("#checks-detail")
        listing = app.screen.query_one("#checks-list-column")
        assert listing.display and not detail.display
        assert "enter detail" in _assert_hints_fit(app, "list")
        await pilot.press("enter")
        await pilot.pause()
        assert detail.display and not listing.display
        assert "sounds · warning" in _screen_text(app)
        assert "[esc] ← Checks" in _screen_text(app)
        assert "esc back" in _assert_hints_fit(app, "detail")
        await pilot.press("escape")
        await pilot.pause()
        assert listing.display and not detail.display
        assert app.settings_screen.tab == "checks"


async def test_checks_wide_tier_keeps_list_and_detail_side_by_side(tmp_path):
    services, _created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.press("enter")
        await pilot.pause()
        listing = app.screen.query_one("#checks-list-column").region
        detail = app.screen.query_one("#checks-detail").region
        assert listing.right <= detail.x
        assert listing.y == detail.y


async def _open_quit(pilot, app, services, created):
    await _record_with_rooms(pilot, services, created, app)
    await pilot.press("q")


async def _open_help(pilot, app, services, created):
    await pilot.press("question_mark")


async def _open_device(pilot, app, services, created):
    await pilot.press("d")


async def _open_rename(pilot, app, services, created):
    await _record_with_rooms(pilot, services, created, app)
    await pilot.press("r")


async def _open_transcribe(pilot, app, services, created):
    await pilot.press("2", "n")


@pytest.mark.parametrize(
    ("open_dialog", "shown"),
    [
        (_open_quit, ("[y] Save and quit",)),
        (_open_help, ("[esc] Close",)),
        (_open_device, ("[enter] Use device",)),
        (_open_rename, ("[enter] Rename",)),
        (_open_transcribe, ("Separate speakers", "Refine text", "[enter] Transcribe")),
    ],
)
async def test_dialogs_stay_four_columns_narrower_than_the_terminal(tmp_path, open_dialog, shown):
    services, created = _services(tmp_path, devices=(("dev-1", "USB microphone"),))
    for number in range(20):
        (tmp_path / f"call-{number:02d}.wav").write_bytes(b"")
    app = _app(tmp_path, services, files_home=tmp_path)
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.pause()
        await open_dialog(pilot, app, services, created)
        await _until(pilot, lambda: app.screen.is_modal)
        await pilot.pause()
        frame = app.screen.query_one("#dialog-frame, .prompt-dialog")
        assert frame.region.width == 56, "each dialog is designed wider than 56 columns"
        assert _layout_problems(app) == []
        for text in shown:
            assert text in _screen_text(app), text
        for session in created:
            session.release.set()


# Fixed slots: a value changes inside its slot and nothing beside it moves.

NARROW_STATUS = EngineStatus("bark-pro-int8", "idle", None, None)
WIDEST_STATUS = EngineStatus("bark-pro-int8", "transcribing 100%", 100.0, int(99.9 * 1024**3))
WIDEST_BADGES = {
    "record": ("●", "00:00:00", "danger"),
    "library": 999,
    "settings": ("9F", "danger"),
}


async def _top_line(pilot, app, sampler, status, badges) -> str:
    sampler.status = status
    app._badges = lambda: badges
    app.refresh_view()
    await pilot.pause()
    return _screen_text(app).splitlines()[0]


@pytest.mark.parametrize("size", TIER_SIZES)
async def test_top_line_slots_keep_every_neighbour_in_place(tmp_path, size):
    services, _created = _services(tmp_path)
    sampler = FakeSampler(NARROW_STATUS)
    app = make_app(tmp_path, services, engine_sampler=sampler)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        empty = await _top_line(pilot, app, sampler, NARROW_STATUS, {})
        widest = await _top_line(pilot, app, sampler, WIDEST_STATUS, WIDEST_BADGES)
        assert len(widest.rstrip()) <= size[0]
        for anchor in ("2 Library", "3 Settings", "cpu", "ram", "bark-pro-int8"):
            assert empty.find(anchor) == widest.find(anchor), anchor
        assert empty.index("idle") == widest.index("transcribing")
        assert "9F" in widest and "●" in widest


async def test_record_slots_keep_every_neighbour_in_place(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)

        def rows():
            text = _screen_text(app).splitlines()
            title = text[app.screen.query_one("#transcript-head").region.y]
            return title, _speaker_bar(app)

        session.lines = [
            TranscriptLine(0.0, 5.0, "", "mic", "room-1", "Room 1", TEXT),
            TranscriptLine(5.0, 6.0, "", "mic", "room-2", "Room 2", TEXT),
        ]
        app.refresh_view()
        await pilot.pause()
        title, bar = rows()
        # 99 speakers, and a first speaker with more than 100 minutes of talk.
        session.lines = [
            TranscriptLine(0.0, 6000.0, "", "mic", "room-1", "Room 1", TEXT),
            *(
                TranscriptLine(6000.0 + i, 6001.0 + i, "", "mic", f"room-{i}", f"Room {i}", TEXT)
                for i in range(2, 100)
            ),
        ]
        app.refresh_view()
        await pilot.pause()
        widest_title, widest_bar = rows()
        assert widest_bar.startswith("Room 1 1h40m   Room 2 ")
        assert bar.index("Room 2") == widest_bar.index("Room 2")
        assert title.index("speakers") == widest_title.index("speakers")
        assert title.index("[r] Rename") == widest_title.index("[r] Rename")
        session.release.set()


@pytest.mark.parametrize("size", [(100, 30), (60, 16)])
async def test_record_status_line_keeps_the_clock_and_buttons_in_place(tmp_path, size):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        clock = app.screen.query_one("#rec-clock-line")
        primary = app.screen.query_one("#rec-primary")
        secondary = app.screen.query_one("#rec-secondary")
        idle = (clock.region.x, primary.region.x, secondary.region.x)
        session = await _record_with_rooms(pilot, services, created, app)
        await pilot.press("enter")
        await _until(pilot, session.stop_entered.is_set)
        session.release.set()
        await _until(pilot, lambda: not services.stopping_sessions)
        services.failed_stops.append((session, "No space left on device"))
        app.refresh_view()
        await pilot.pause()
        assert app.record_screen.record_state() == "failed"
        assert "! SAVE FAILED" in _screen_text(app)
        failed = (clock.region.x, primary.region.x, secondary.region.x)
        assert idle == failed


def test_level_and_peak_slots_keep_dbfs_and_peak_in_place():
    model = SpectrumMeterModel("mic", "Default input")
    model.set_state("on")
    empty = model.level_text
    model.feed(np.full(1600, 10 ** (-99.9 / 20), dtype=np.float32))
    widest = model.level_text
    assert widest == " -99.9 dBFS  peak  -99.9"
    for anchor in ("dBFS", "peak"):
        assert empty.index(anchor) == widest.index(anchor)
    assert len(empty) == len(widest)


def test_checks_count_slots_keep_each_word_in_place():
    def summary(count):
        report = SimpleNamespace(
            ok_count=count,
            warn_count=count,
            fail_count=count,
            checked_at=datetime(2026, 11, 12, 13, 40),
        )
        return ChecksTab.summary_text(SimpleNamespace(report=report, checking=False)).plain

    one, widest = summary(1), summary(99)
    for anchor in ("pass", "warn", "fail", "last run"):
        assert one.index(anchor) == widest.index(anchor), anchor


# Review fixes of PR 51

FIVE_SPEAKERS = [
    TranscriptLine(i * 6.0, i * 6.0 + 5, "", "mic", f"room-{i % 5 + 1}", f"Room {i % 5 + 1}", TEXT)
    for i in range(20)
]


async def _record_five(pilot, services, created, app):
    session = await _record_with_rooms(pilot, services, created, app)
    session.lines = list(FIVE_SPEAKERS)
    app.refresh_view()
    await pilot.pause()
    return session


@pytest.mark.parametrize("size", [(150, 16), (120, 16), (120, 24), (80, 16), (80, 20)])
async def test_record_gives_the_transcript_six_lines_in_a_short_terminal(tmp_path, size):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        session = await _record_five(pilot, services, created, app)
        assert app.screen.query_one("#transcript").region.height >= 6
        assert _layout_problems(app) == []
        session.release.set()


@pytest.mark.parametrize("size", [(150, 45), (150, 16), (100, 30), (60, 16)])
async def test_record_buttons_stay_in_place_when_pause_becomes_resume(tmp_path, size):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        session = await _record_five(pilot, services, created, app)

        def positions():
            return tuple(
                app.screen.query_one(selector).region.x
                for selector in ("#rec-primary", "#rec-secondary")
            )

        recording = positions()
        await pilot.press("space")
        await _until(pilot, lambda: session.paused)
        app.refresh_view()
        await pilot.pause()
        assert "▶ Resume" in _screen_text(app)
        assert positions() == recording
        session.release.set()


async def test_checks_narrow_summary_is_never_cut(tmp_path):
    services, _created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()

        def summary_row():
            row = app.screen.query_one("#checks-summary-row").region.y
            return _screen_text(app).splitlines()[row]

        listed = summary_row()
        assert "last run 13:21" in listed and "…" not in listed
        await pilot.press("enter")
        await pilot.pause()
        detail = summary_row()
        assert "…" not in detail
        assert "last run" not in detail
        assert " 6 pass ·  1 warn ·  1 fail" in detail


async def test_layout_problems_check_rows_inside_a_scroll_container(tmp_path):
    services, _created = _services(tmp_path)
    report = _board_report()
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        assert _region_problems(app, app.checks_tab) == []
        row = app.screen.query_one("#checks-engine")
        row.styles.offset = (8, 0)
        await pilot.pause()
        assert any(p.startswith("checks-engine leaves") for p in _layout_problems(app))
        row.styles.offset = (0, -2)
        await pilot.pause()
        overlaps = [p for p in _layout_problems(app) if " overlaps " in p]
        assert any("checks-engine" in p for p in overlaps), overlaps


async def test_narrow_speaker_row_is_one_line_with_a_count_of_the_rest(tmp_path):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(60, 16)) as pilot:
        session = await _record_with_rooms(pilot, services, created, app)
        rows = _speaker_bar(app).splitlines()
        assert len(rows) == 1
        assert rows[0].startswith("Room 1  0:10   Room 2")
        shown = rows[0].count("Room ")
        assert rows[0].endswith(f"   +{12 - shown}")
        session.failed_phrase_count = 2
        app.refresh_view()
        await pilot.pause()
        rows = _speaker_bar(app).splitlines()
        assert len(rows) == 2
        assert rows[1] == "! 2 phrases failed"
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert len(_speaker_bar(app).splitlines()) > 2, "the medium tier keeps the wrap"
        session.release.set()


# Review fixes of PR 51, round 2

WARNINGS = (
    "13:12:04 WARN live: source_silent",
    "11:48:30 ERROR live: system_source_failed",
    "10:02:11 WARN live: source_silent",
)


@pytest.mark.parametrize("size", [(150, 16), (120, 16), (120, 24)])
async def test_checks_fit_a_wide_short_terminal(tmp_path, size):
    services, _created = _services(tmp_path)
    report = _board_report(WARNINGS)
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        selected = app.checks_tab.selected
        assert selected.label == "sounds", "the check with Fix, Test and a path"
        assert _region_problems(app, app.checks_tab) == []
        bottom = app.screen.query_one("#checks-dialog-buttons").region
        assert bottom.bottom == app.screen.query_one("#checks-detail").content_region.bottom


@pytest.mark.parametrize("size", [(120, 35), (150, 45)])
async def test_checks_wide_keeps_the_dialog_buttons_at_the_bottom_of_the_detail(tmp_path, size):
    services, _created = _services(tmp_path)
    report = _board_report(WARNINGS)
    app = _app(tmp_path, services, doctor_probe=lambda _config: report)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3", "left")
        await _until(pilot, lambda: app.checks_tab.report is not None)
        await pilot.pause()
        detail = app.screen.query_one("#checks-detail").content_region
        row = app.screen.query_one("#checks-dialog-buttons").region
        assert row.bottom == detail.bottom
        assert "[Q] Quick setup…" in _screen_text(app).splitlines()[row.y]
        assert _region_problems(app, app.checks_tab) == []


def test_meter_head_keeps_the_device_in_place_for_each_state():
    for source, device in (("mic", "Default input"), ("system", "default output")):
        model = SpectrumMeterModel(source, device)
        places = set()
        for state in ("on", "off", "idle"):
            model.set_state(state)
            places.add(model.head[0].index(device))
        assert len(places) == 1, source


@pytest.mark.parametrize("size", [(120, 35), (100, 30)])
async def test_system_head_does_not_change_with_speech(tmp_path, size):
    services, created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        session = await _record_five(pilot, services, created, app)

        def head():
            row = app.screen.query_one("#system-meter").content_region.y
            return _screen_text(app).splitlines()[row]

        quiet = head()
        assert "default output" in quiet
        session.speech_detected["system"] = True
        app.refresh_view()
        await pilot.pause()
        speech = head()
        assert "● speech" in speech
        assert speech.index("default output") == quiet.index("default output")
        session.release.set()
