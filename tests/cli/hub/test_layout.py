# SPDX-License-Identifier: GPL-3.0-or-later
"""The hub layout: full-width transcripts, speaker bar, stacked Library and top summaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from rich.text import Text
from textual.app import App
from textual.widgets import Button, Input, Select, Static

from stenographer.cli.hub.widgets.speaker_bar import SpeakerBar
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from tests.cli.hub.support import _fields, _screen_text, _speaker_bar, make_app
from tests.cli.hub.test_checks_tab import _board_report
from tests.cli.hub.test_library import FakeJob
from tests.cli.hub.test_library import FakeServices as LibraryServices
from tests.cli.hub.test_record_screen import _app, _services, _until

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


def _scrolls(node) -> bool:
    return node.styles.overflow_y in {"auto", "scroll"}


def _layout_problems(app) -> list[str]:
    """Return each shown widget outside the screen or its parent, and each cut button label."""
    screen = app.screen
    problems = []
    for widget in screen.query("*"):
        region = widget.region
        if not widget.display or not region.area:
            continue
        if any(_scrolls(node) for node in widget.ancestors if node is not screen):
            continue
        name = widget.id or type(widget).__name__
        if not screen.region.contains_region(region):
            problems.append(f"{name} leaves the screen: {region}")
        parent = widget.parent
        if parent is not screen and not parent.content_region.contains_region(region):
            problems.append(f"{name} leaves {parent.id}: {region}")
        if isinstance(widget, Button) and widget.label.cell_length > widget.content_size.width:
            problems.append(f"{name} cuts its label: {widget.label}")
    return problems


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
        assert bar.size.height == 2
        rows = str(bar.render()).splitlines()
        assert rows[0].startswith("Room 1 0:")
        assert rows[-1].endswith("! 2 phrases failed   ! mic audio not saved")
        for number in range(1, 13):
            assert f"Room {number} 0:" in "\n".join(rows), "label and time stay on one row"
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
        assert "transcript · 12 speakers" in _screen_text(app)
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
        assert "transcript · 12 speakers" in _screen_text(app)


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


async def _open_transcribe_count(pilot, app):
    await pilot.press("2", "n")
    await pilot.pause()
    app.screen.action_edit_count()
    return "#transcribe-count"


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
        _open_transcribe_count,
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
        # All digits, so that the integer input of the speaker count takes it too.
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
    async with app.run_test(size=(150, 45)) as pilot:
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

        long_value = "alpha-" * 12
        row.set_value(long_value, changed=False)
        await pilot.pause()
        assert long_value in _screen_text(app), "a value without a note stays on one row"


async def test_settings_row_shows_the_word_editing_while_its_input_is_open(tmp_path):
    services, _created = _services(tmp_path)
    app = _app(tmp_path, services)
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.press("3", "enter")
        await pilot.pause()
        row = next(line for line in _screen_text(app).splitlines() if "Agent key" in line)
        assert row.split("│")[1].split()[-1] == "editing"
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
        assert str(summary.render()) == "config.toml · 0 unsaved changes · backups none yet"
