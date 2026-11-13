# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library table and the open session: views, keys, busy rules, titles, play and slots."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import timedelta

import pytest
from textual.widgets import Input, Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.title_dialog import TitleDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.lib.config.models import Config
from stenographer.lib.files.models import FileJobProgress
from stenographer.lib.sessions import SessionStore
from tests.cli.hub.support import _screen_text, make_app
from tests.cli.hub.test_library import (
    REC_LIVE,
    FakeJob,
    FakeServices,
    _library,
    _private_tmp,
    _until,
    _write_file_session,
    _write_rec,
)
from tests.cli.hub.test_session_jobs import FakePlatform, FakePlayer

pytestmark = pytest.mark.usefixtures("utc")

TITLE = "Caterer venue booking"


async def _open(pilot, app, count: int) -> None:
    await pilot.press("2")
    await _until(pilot, lambda: len(app.library_screen.entries) == count, "list did not load")
    await _until(pilot, lambda: app.library_screen.detail is not None, "detail did not load")
    app.refresh_view()
    await pilot.pause()


async def _settle(pilot, app) -> None:
    app.refresh_view()
    await pilot.pause()
    await pilot.pause()


def _button(app, button_id: str) -> HubButton:
    return app.screen.query_one(f"#{button_id}", HubButton)


def _notices(app) -> list[str]:
    return [str(notice.message) for notice in app._notifications]


def _line_of(app, needle: str) -> str:
    text = _screen_text(app)
    for line in text.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"{needle!r} is not on the screen:\n{text}")


def _column(app, needle: str) -> int:
    return _line_of(app, needle).index(needle)


# Views


async def test_enter_opens_the_session_and_escape_returns_with_the_same_row(tmp_path):
    root, sessions = _library(tmp_path)
    SessionStore(root).set_title(sessions["live"], TITLE)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        screen = app.library_screen
        await pilot.press("down")
        assert screen.selected_id == sessions["live"]
        await pilot.press("enter")
        await _settle(pilot, app)
        assert screen.opened
        assert not app.screen.query_one("#library-table-view").display
        assert app.screen.query_one("#library-session").display
        assert TITLE in _line_of(app, "[e] Edit title…")
        assert "[esc] ← Library" in _screen_text(app)

        await pilot.press("escape")
        await _settle(pilot, app)
        assert not screen.opened
        assert screen.selected_id == sessions["live"]
        assert _line_of(app, TITLE).lstrip("│ ").startswith("▶")


async def test_a_click_on_back_returns_and_show_library_opens_the_session(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        app.show_library(sessions["file"])
        await _until(pilot, lambda: app.library_screen.opened)
        assert app.library_screen.selected_id == sessions["file"]
        await _settle(pilot, app)
        await pilot.click("#library-back")
        await _settle(pilot, app)
        assert not app.library_screen.opened


async def test_up_and_down_scroll_the_open_transcript_and_select_in_the_table(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("enter", "down")
        await _settle(pilot, app)
        assert app.library_screen.selected_id == sessions["relabeled"]
        await pilot.press("escape", "down")
        assert app.library_screen.selected_id == sessions["live"]


ACTION_KEYS = {
    "p": lambda app, services, session: ("play", session) in services.actions,
    "e": lambda app, services, session: isinstance(app.screen, TitleDialog),
    "r": lambda app, services, session: isinstance(app.screen, RenameDialog),
    "d": lambda app, services, session: ("diarization", session) in services.actions,
    "t": lambda app, services, session: ("re-transcribe", session) in services.actions,
    "x": lambda app, services, session: isinstance(app.screen, ExportDialog),
    "delete": lambda app, services, session: isinstance(app.screen, QuitConfirm),
}


@pytest.mark.parametrize("opened", [False, True], ids=["table", "session"])
@pytest.mark.parametrize("key", list(ACTION_KEYS))
async def test_each_action_key_acts_in_the_table_and_in_the_open_session(tmp_path, key, opened):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.release_job.set()
    app = make_app(tmp_path, services)
    session = sessions["relabeled"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        assert app.library_screen.selected_id == session
        if opened:
            await pilot.press("enter")
            await _settle(pilot, app)
        await pilot.press(key)
        await _until(pilot, lambda: ACTION_KEYS[key](app, services, session), f"{key} did nothing")


# Busy


async def test_a_busy_session_dims_what_cannot_run_and_its_keys_show_the_notice(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    session = sessions["relabeled"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("enter")
        assert app.try_acquire_session(session, "test")
        await _settle(pilot, app)
        dimmed = {
            "library-title-button",
            "library-rename",
            "library-rediarize",
            "library-retranscribe",
            "library-delete",
        }
        for button_id in (*dimmed, "library-play", "library-export"):
            assert _button(app, button_id).disabled == (button_id in dimmed), button_id
            assert "busy" not in _button(app, button_id).label.plain
        for key in ("e", "r", "d", "t", "delete"):
            before = _notices(app).count("session busy")
            await pilot.press(key)
            await pilot.pause()
            assert _notices(app).count("session busy") == before + 1, key
            assert app.screen is app.library_screen, key


async def test_a_running_revision_job_turns_delete_into_cancel_job(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    app = make_app(tmp_path, services)
    live = sessions["live"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        screen = app.library_screen
        job = await asyncio.to_thread(screen.submit_file, root / live / "mic.flac")
        await _until(
            pilot, lambda: screen.entry(live) is not None and screen.entry(live).job is job
        )
        screen.select_entry(live)
        await pilot.press("enter")
        job.state = "running"
        job.progress = FileJobProgress("transcribe", 61, ())
        await _until(pilot, lambda: "61%" in _screen_text(app), "no job percent")
        await _settle(pilot, app)
        delete = _button(app, "library-delete")
        assert delete.label.plain == "[del] Cancel job…"
        assert not delete.disabled
        assert "transcribing" in _line_of(app, "[esc] ← Library")
        await pilot.press("delete")
        await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
        await pilot.press("y")
        await _until(pilot, lambda: job.cancel_requested)


# Titles


async def test_e_sets_changes_and_removes_a_title(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    live = sessions["live"]
    metadata_path = root / live / "session.json"
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        screen = app.library_screen
        screen.select_entry(live)
        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        assert app.screen.query_one("#title-input", Input).value == ""
        await pilot.press(*TITLE, "enter")
        await _until(pilot, lambda: TITLE in metadata_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert (metadata["title"], metadata["title_source"]) == (TITLE, "user")
        await _until(pilot, lambda: TITLE in _screen_text(app), "the table shows no title")
        assert not any("complete" in notice for notice in _notices(app))

        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        field = app.screen.query_one("#title-input", Input)
        assert field.value == TITLE
        field.value = "Catering budget"
        await pilot.press("enter")
        await _until(pilot, lambda: "Catering budget" in _screen_text(app))

        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        app.screen.query_one("#title-input", Input).value = ""
        await pilot.press("enter")
        await _until(pilot, lambda: "Catering budget" not in _screen_text(app))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "title" not in metadata and "title_source" not in metadata


async def test_escape_in_the_title_dialog_keeps_the_title(tmp_path):
    root, sessions = _library(tmp_path)
    SessionStore(root).set_title(sessions["relabeled"], TITLE)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        app.screen.query_one("#title-input", Input).value = "Other"
        await pilot.press("escape")
        await pilot.pause(0.1)
    assert SessionStore(root).read(sessions["relabeled"]).summary.title == TITLE


async def test_search_matches_a_title(tmp_path):
    root, sessions = _library(tmp_path)
    SessionStore(root).set_title(sessions["interrupted"], TITLE)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("slash", *"caterer")
        screen = app.library_screen
        await _until(
            pilot, lambda: [e.entry_id for e in screen.entries] == [sessions["interrupted"]]
        )


async def test_entries_without_a_title_show_a_dash_or_their_file_name(tmp_path):
    root, sessions = _library(tmp_path)
    for session_id in sessions.values():
        assert "title" not in (root / session_id / "session.json").read_text(encoding="utf-8")
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        when = REC_LIVE.astimezone()
        row = _line_of(app, f"{when:%d %b %H:%M}")
        assert row.split()[6:10] == ["Speaker", "1,", "You", "—"]
        assert "meeting.wav" in _screen_text(app)


async def test_the_title_is_not_in_the_log(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        await pilot.press(*TITLE, "enter")
        session = sessions["relabeled"]
        await _until(pilot, lambda: SessionStore(root).read(session).summary.title == TITLE)
        await pilot.press("enter", "slash", *"caterer")
        await pilot.pause(0.2)
    assert caplog.records, "the hub logged nothing, so the check proves nothing"
    assert "caterer" not in caplog.text.casefold()


# Play


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _player_app(tmp_path, monkeypatch, start_player):
    monkeypatch.setattr(tempfile, "tempdir", str(_private_tmp(tmp_path)))
    root = tmp_path / "sessions"
    session = _write_rec(root, REC_LIVE).name
    clock = _Clock()
    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_store=SessionStore(root),
        player_factory=start_player,
        clock=clock,
    )
    return make_app(tmp_path, services), services, clock, session


async def test_play_shows_stop_and_the_position_until_the_player_ends(tmp_path, monkeypatch):
    players: list[FakePlayer] = []

    def start_player(command):
        players.append(FakePlayer())
        return players[-1]

    app, services, clock, _session = _player_app(tmp_path, monkeypatch, start_player)
    try:
        async with app.run_test(size=(120, 35)) as pilot:
            await _open(pilot, app, 1)
            await pilot.press("enter")
            await _settle(pilot, app)
            play = _button(app, "library-play")
            assert play.label.plain == "[p] ▶ Play 00:00:00 / 00:00:03"
            rename_x = _button(app, "library-rename").region.x

            await pilot.press("p")
            await _until(pilot, lambda: "■ Stop" in play.label.plain, "no Stop label")
            assert play.label.plain == "[p] ■ Stop 00:00:00 / 00:00:03"
            clock.now += 2.4
            await _until(pilot, lambda: "00:00:02 /" in play.label.plain, "position did not move")
            await pilot.pause()
            assert _button(app, "library-rename").region.x == rename_x
            # The position never passes the duration.
            clock.now += 60
            await _until(pilot, lambda: "00:00:03 / 00:00:03" in play.label.plain)

            # The player ends by itself: Play and 00:00:00 come back; the timer stops.
            players[0].finished.set()
            await _until(pilot, lambda: "▶ Play 00:00:00" in play.label.plain, "no Play label")
            await _until(pilot, lambda: app.library_screen._play_timer is None, "timer runs")

            # Stop by key.
            await pilot.press("p")
            await _until(pilot, lambda: "■ Stop" in play.label.plain)
            await pilot.press("p")
            await _until(pilot, lambda: players[1].terminated, "p did not stop")
            await _until(pilot, lambda: "▶ Play 00:00:00" in play.label.plain)
            assert _button(app, "library-rename").region.x == rename_x
    finally:
        services.stop_session_playback()


async def test_a_player_that_does_not_start_shows_the_notice_and_no_position(tmp_path, monkeypatch):
    def start_player(command):
        raise FileNotFoundError("pw-play")

    app, _services, clock, _session = _player_app(tmp_path, monkeypatch, start_player)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 1)
        await pilot.press("enter", "p")
        await _until(pilot, lambda: any("Could not play" in n for n in _notices(app)))
        clock.now += 5
        await _settle(pilot, app)
        assert _button(app, "library-play").label.plain == "[p] ▶ Play 00:00:00 / 00:00:03"
        assert app.library_screen._play_timer is None


async def test_the_narrow_play_button_has_no_position(tmp_path, monkeypatch):
    app, _services, _clock, _session = _player_app(tmp_path, monkeypatch, lambda c: FakePlayer())
    async with app.run_test(size=(60, 16)) as pilot:
        await _open(pilot, app, 1)
        await pilot.press("enter")
        await _settle(pilot, app)
        assert _button(app, "library-play").label.plain == "[p] ▶ Play"


# Slots


def _job_services(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    job = FakeJob("file-1", tmp_path / "sources" / "lecture.mp3", percent=0)
    services.jobs.append(job)
    return root, sessions, services, job


async def test_the_job_percent_and_the_head_values_keep_their_neighbours(tmp_path):
    _root, _sessions, services, job = _job_services(tmp_path)
    app = make_app(tmp_path, services)
    screen = app.library_screen
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(screen.entries) == 5)
        await _settle(pilot, app)
        positions = []
        for state, percent in (("queued", 0), ("running", 0), ("running", 100)):
            job.state = state
            job.progress = FileJobProgress("transcribe", percent, ())
            screen.poll_jobs()
            await _settle(pilot, app)
            row = _line_of(app, "lecture.mp3")
            positions.append((row.index("file"), row.index("lecture.mp3"), row.index("transcribe")))
        assert len(set(positions)) == 1, positions

        head = []
        for count, total in ((0, 0), (999, int(999.9 * 1024**3))):
            screen._all_count = count
            screen.summaries = tuple(
                type(s)(**{**s.__dict__, "audio_size_bytes": total // len(screen.summaries)})
                for s in screen.summaries
            )
            await _settle(pilot, app)
            line = _line_of(app, "[n] + Transcribe a file…")
            assert f"{count} entries" in line
            region = app.screen.query_one("#library-count").region
            head.append((line.index("[n]"), region.x, region.width, line.index("audio")))
        assert head[0] == head[1], head


async def test_the_row_state_and_the_selection_marker_keep_the_columns(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    screen = app.library_screen
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        when = REC_LIVE.astimezone()
        date = f"{when:%d %b %H:%M}"
        unselected = _line_of(app, date)
        screen.select_entry(sessions["live"])
        await _settle(pilot, app)
        selected = _line_of(app, date)
        assert selected.replace("▶", " ") == unselected

        state_column = unselected.index("live")
        assert app.try_acquire_session(sessions["live"], "test")
        screen._session_work[sessions["live"]] = "re-transcribe"
        await _settle(pilot, app)
        busy = _line_of(app, date)
        assert busy.index("re-transcribe") == state_column
        assert busy.replace("re-transcribe", "live         ") == selected


async def test_the_session_state_keeps_the_date_in_place(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    screen = app.library_screen
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        when = f"{REC_LIVE.astimezone():%d %b %Y %H:%M}"
        screen.select_entry(sessions["live"])
        await pilot.press("enter")
        await _until(
            pilot, lambda: screen.detail is not None and screen._detail_id == sessions["live"]
        )
        await _settle(pilot, app)
        plain = _column(app, when)
        screen._session_work[sessions["live"]] = "re-transcribe"
        await _settle(pilot, app)
        assert "re-transcribe" in _line_of(app, when)
        assert _column(app, when) == plain


# Fresh files and old sessions


async def test_a_file_job_row_opens_with_its_file_name_and_dimmed_buttons(tmp_path):
    _root, _sessions, services, job = _job_services(tmp_path)
    job.state = "queued"
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(app.library_screen.entries) == 5)
        assert app.library_screen.selected_id == "job:file-1"
        await pilot.press("enter")
        await _settle(pilot, app)
        assert "lecture.mp3" in _line_of(app, "[e] Edit title…")
        assert "queued" in _line_of(app, "[esc] ← Library")
        for button_id in ("library-play", "library-title-button", "library-rename"):
            assert _button(app, button_id).disabled, button_id
        assert _button(app, "library-delete").label.plain == "[del] Cancel job…"
        assert not _button(app, "library-delete").disabled


async def test_a_deleted_open_session_returns_to_the_table(tmp_path):
    root, sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("enter", "delete")
        await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
        await pilot.press("y")
        await _until(pilot, lambda: len(app.library_screen.entries) == 3)
        await _settle(pilot, app)
        assert not app.library_screen.opened
        assert not (root / sessions["relabeled"]).exists()


async def test_a_session_with_a_new_title_sorts_and_lists_as_before(tmp_path):
    root = tmp_path / "sessions"
    older = _write_rec(root, REC_LIVE).name
    newer = _write_rec(root, REC_LIVE + timedelta(hours=1)).name
    SessionStore(root).set_title(older, TITLE)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 2)
        assert [entry.entry_id for entry in app.library_screen.entries] == [newer, older]
        assert _line_of(app, TITLE).index(TITLE) > 0


async def test_a_file_session_without_a_title_shows_its_file_name_in_the_open_view(tmp_path):
    root = tmp_path / "sessions"
    session = _write_file_session(root, tmp_path, name="standup.flac")
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 1)
        await pilot.press("enter")
        await _settle(pilot, app)
        assert "standup.flac" in _line_of(app, "[e] Edit title…")
        assert app.library_screen.selected_id == session


async def test_the_head_shows_no_sessions_folder(tmp_path):
    root, _sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(150, 45)) as pilot:
        await _open(pilot, app, 4)
        assert str(root) not in _screen_text(app)
        assert "sessions" not in _line_of(app, "entries")
        assert not app.screen.query("Sparkline")
        static_ids = {widget.id for widget in app.screen.query(Static)}
        assert not {"library-mic", "library-sys"} & static_ids


async def test_the_open_transcript_shows_speakers_bold_in_their_colour_with_no_frame_inside(
    tmp_path,
):
    root, _sessions = _library(tmp_path)
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(150, 45)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("enter")
        await _settle(pilot, app)
        view = app.screen.query_one("#library-session")
        assert view.styles.border.top[0] == "round"
        framed = [
            widget for widget in view.query("*") if widget.styles.border.top[0] not in ("", "none")
        ]
        assert framed == []
        content = app.screen.query_one("#transcript-scroll-content", Static)
        lines = content.render_lines(content.region.reset_offset)
        segments = [segment for strip in lines for segment in strip]
        speaker = next(segment for segment in segments if segment.text.strip() == "Speaker 1")
        assert speaker.style.bold
        assert speaker.style.color.triplet == (255, 175, 95)
