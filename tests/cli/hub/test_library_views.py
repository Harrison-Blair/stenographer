# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library table and the open session: views, keys, busy rules, titles, play and slots."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import threading
from datetime import timedelta

import numpy as np
import pytest
import soundfile as sf
from textual.widgets import Input, Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.session_titles import THREAD_NAME
from stenographer.cli.hub.title_dialog import TitleDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.lib.config.models import Config
from stenographer.lib.files.models import FileJobProgress
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.refine.errors import RefineTransportError
from stenographer.lib.sessions import SessionStore
from tests.cli.hub.support import _layout_problems, _screen_text, make_app
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
    root = tmp_path / "sessions"
    writer = SessionWriter.open(tmp_path, REC_LIVE)
    for index in range(60):
        writer.append_line(
            TranscriptLine(index, index + 1, "", "mic", "you", "You", f"line {index}")
        )
    writer.close()
    older = _write_rec(root, REC_LIVE - timedelta(days=1)).name
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 2)
        await pilot.press("enter", "home")
        await _settle(pilot, app)
        transcript = app.screen.query_one("#library-transcript")
        assert transcript.max_scroll_y > 2, "the transcript must be longer than its view"
        assert transcript.scroll_y == 0
        await pilot.press("down")
        assert transcript.scroll_y == 1
        await pilot.press("down", "up", "down")
        assert transcript.scroll_y == 2
        assert app.library_screen.selected_id == writer.path.name
        await pilot.press("escape", "down")
        assert app.library_screen.selected_id == older


ACTION_KEYS = {
    "p": lambda app, services, session: ("play", session) in services.actions,
    "e": lambda app, services, session: isinstance(app.screen, TitleDialog),
    "g": lambda app, services, session: len(services.title_request.calls) == 1,
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
            "library-generate-button",
            "library-rename",
            "library-rediarize",
            "library-retranscribe",
            "library-delete",
        }
        for button_id in (*dimmed, "library-play", "library-export"):
            assert _button(app, button_id).disabled == (button_id in dimmed), button_id
            assert "busy" not in _button(app, button_id).label.plain
        for key in ("e", "g", "r", "d", "t", "delete"):
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
        assert "re-transcribe ·" in _line_of(app, "[esc] ← Library")
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


# Generated titles

GENERATED = "Alpha bravo, delta echo"


def _title_cell(app, session_id: str) -> str:
    """Return the first line of the title cell of a session in the table."""
    library = app.library_screen
    when = library.entry(session_id).summary.started_at.astimezone()
    heading = _screen_text(app).splitlines()[app.screen.query_one("#library-columns").region.y]
    row = _line_of(app, f"{when:%d %b %H:%M}")
    start = heading.index("title")
    return row[start : start + 12]


@pytest.mark.parametrize("opened", [False, True], ids=["table", "session"])
async def test_g_shows_generating_then_stores_a_model_title(tmp_path, opened):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.reply = GENERATED
    services.title_request.release.clear()
    app = make_app(tmp_path, services)
    session = sessions["relabeled"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        if opened:
            await pilot.press("enter")
            await _settle(pilot, app)
        await pilot.press("g")
        await _until(pilot, lambda: services.title_request.started.is_set())
        await _settle(pilot, app)
        if opened:
            title = app.screen.query_one("#library-detail-title", Static)
            assert title.render().plain == "generating…"
            assert title.content.style == StatusToken.TONES["dim"]
            assert _button(app, "library-title-button").disabled
            assert _button(app, "library-generate-button").disabled
        else:
            assert _title_cell(app, session) == "generating… "
            table = app.screen.query_one("#library-list").content
            start = table.plain.index("generating…")
            assert any(
                span.start <= start < span.end and span.style == StatusToken.TONES["dim"]
                for span in table.spans
            )
        [(_host, _model, text, _keep_alive)] = services.title_request.calls
        assert text == "Speaker 1: alpha bravo charlie\nYou: delta echo foxtrot"

        services.title_request.release.set()
        await _until(pilot, lambda: GENERATED in _screen_text(app), "no title")
        summary = SessionStore(root).read(session).summary
        assert (summary.title, summary.title_source) == (GENERATED, "model")
        assert "generating…" not in _screen_text(app)


async def test_e_and_g_show_session_busy_while_the_title_generates_and_other_keys_act(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.release.clear()
    app = make_app(tmp_path, services)
    session = sessions["relabeled"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("g")
        await _until(pilot, lambda: services.title_request.started.is_set())
        for key in ("e", "g"):
            before = _notices(app).count("session busy")
            await pilot.press(key)
            await pilot.pause()
            assert _notices(app).count("session busy") == before + 1, key
            assert app.screen is app.library_screen, key
        await pilot.press("p")
        await _until(pilot, lambda: ("play", session) in services.actions, "p did nothing")
        await pilot.press("r")
        await _until(pilot, lambda: isinstance(app.screen, RenameDialog), "r did nothing")
        services.title_request.release.set()
    assert len(services.title_request.calls) == 1


async def test_g_on_a_typed_title_asks_first(tmp_path):
    root, sessions = _library(tmp_path)
    session = sessions["relabeled"]
    SessionStore(root).set_title(session, TITLE)
    services = FakeServices(root)
    services.title_request.reply = GENERATED
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("g")
        await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
        assert "Replace the title you typed with a generated title?" in _screen_text(app)
        await pilot.press("n")
        await _until(pilot, lambda: app.screen is app.library_screen)
        await pilot.pause(0.2)
        assert services.title_request.calls == []

        await pilot.press("g")
        await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
        await pilot.press("y")
        await _until(pilot, lambda: GENERATED in _screen_text(app), "no title")
    summary = SessionStore(root).read(session).summary
    assert (summary.title, summary.title_source) == (GENERATED, "model")


async def test_g_on_a_model_title_asks_nothing(tmp_path):
    root, sessions = _library(tmp_path)
    session = sessions["relabeled"]
    SessionStore(root).set_title(session, TITLE, source="model")
    services = FakeServices(root)
    services.title_request.reply = GENERATED
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("g")
        await _until(pilot, lambda: GENERATED in _screen_text(app), "no title")
        assert not isinstance(app.screen, QuitConfirm)


async def test_a_session_deleted_while_its_title_generates_drops_the_title(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.release_job.set()
    services.title_request.release.clear()
    app = make_app(tmp_path, services)
    session = sessions["relabeled"]
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("g")
        await _until(pilot, lambda: services.title_request.started.is_set())
        await pilot.press("delete")
        await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
        await pilot.press("y")
        await _until(pilot, lambda: not (root / session).exists(), "not deleted")
        services.title_request.release.set()
        await _until(pilot, lambda: not services.titles.generating, "still generating")
        await _until(pilot, lambda: len(app.library_screen.entries) == 3)
        await _settle(pilot, app)
        assert not (root / session).exists()
        assert _notices(app) == ["Delete complete."]


async def test_a_failure_of_g_shows_a_notice(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.reply = RefineTransportError("ollama could not be reached")
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("g")
        notice = "Could not generate a title: ollama could not be reached."
        await _until(pilot, lambda: notice in _notices(app), "no notice")


async def test_a_session_without_transcript_lines_gets_no_request_and_a_notice(tmp_path):
    root = tmp_path / "sessions"
    writer = SessionWriter.open(tmp_path, REC_LIVE)
    writer.close()
    services = FakeServices(root)
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 1)
        await pilot.press("g")
        notice = "This session has no transcript lines."
        await _until(pilot, lambda: notice in _notices(app), "no notice")
    assert services.title_request.calls == []


async def test_a_title_stored_between_two_polls_shows_at_the_next_poll(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.reply = "Kilo lima"
    services.installed_models.add(services.config.refine.model)
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        # The event loop does not run while the request starts and ends.
        services.titles.generate_auto(sessions["relabeled"])
        for thread in threading.enumerate():
            if thread.name == THREAD_NAME:
                thread.join(timeout=5)
        assert SessionStore(root).read(sessions["relabeled"]).summary.title == "Kilo lima"
        await _until(pilot, lambda: "Kilo lima" in _screen_text(app), "the title does not show")


async def test_a_g_that_fails_between_two_polls_clears_generating_at_the_next_poll(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.reply = RefineTransportError("ollama could not be reached")
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("enter")
        await _settle(pilot, app)
        # One idle poll runs before g.
        await pilot.pause(0.15)
        # The event loop does not run while g starts, fails, and its thread ends.
        app.library_screen.action_session_generate_title()
        for thread in threading.enumerate():
            if thread.name == THREAD_NAME:
                thread.join(timeout=5)
        assert not services.titles.generating
        # Shorter than the one-second engine refresh: only the poll draws.
        notice = "Could not generate a title: ollama could not be reached."
        await _until(pilot, lambda: notice in _notices(app), "no notice")
        await pilot.pause(0.15)
        title = app.screen.query_one("#library-detail-title", Static)
        assert title.content.plain != "generating…"
        assert not _button(app, "library-title-button").disabled
        assert not _button(app, "library-generate-button").disabled


async def test_a_finished_file_job_gets_an_automatic_title(tmp_path):
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    services.title_request.reply = GENERATED
    services.installed_models.add(services.config.refine.model)
    job = FakeJob("file-1", tmp_path / "sources" / "meeting.wav")
    services.jobs.append(job)
    app = make_app(tmp_path, services)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(app.library_screen.entries) == 5, "list did not load")
        # The poll must see the job run before it ends.
        await _until(pilot, lambda: app.library_screen._job_states.get("file-1") == "running")
        new_id = _write_file_session(root, tmp_path, name="meeting.wav")
        job.session_id = new_id
        job.state = "completed"
        store = SessionStore(root)
        await _until(pilot, lambda: store.read(new_id).summary.title, "no automatic title")
    summary = SessionStore(root).read(new_id).summary
    assert (summary.title, summary.title_source) == (GENERATED, "model")


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
            shown = "queued" if state == "queued" else f"{percent}%"
            assert f" {shown}  file " in row, row
            positions.append((row.index("file"), row.index("lecture.mp3"), row.index("transcribe")))
        assert len(set(positions)) == 1, positions

        head = []
        for count, total, size in ((0, 0, "0 M"), (999, int(999.9 * 1024**3), "999.9 G")):
            screen._all_count = count
            screen.summaries = tuple(
                type(s)(**{**s.__dict__, "audio_size_bytes": total // len(screen.summaries)})
                for s in screen.summaries
            )
            await _settle(pilot, app)
            line = _line_of(app, "[n] + Transcribe a file…")
            assert f"{count} entries" in line
            assert f" {size} audio" in line, line
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


def test_session_playback_answers_while_the_play_audio_is_prepared(tmp_path, monkeypatch):
    _app, services, _clock, session = _player_app(tmp_path, monkeypatch, lambda c: FakePlayer())
    preparing = threading.Event()
    release = threading.Event()
    play_file = tmp_path / "play.wav"
    play_file.write_bytes(b"")

    class _HeldJobs:
        def write_play_audio(self, session_id):
            preparing.set()
            assert release.wait(5), "the test did not release the preparation"
            return play_file

    services._session_jobs = _HeldJobs()
    answered = threading.Event()
    toggle = threading.Thread(target=services.toggle_session_playback, args=(session,))
    toggle.start()
    try:
        assert preparing.wait(5)

        def ask():
            services.session_playback()
            answered.set()

        threading.Thread(target=ask, daemon=True).start()
        # The answer comes while the preparation is still held.
        assert answered.wait(5), "session_playback() waited for the play audio"
        assert not release.is_set()
        assert services.session_playback() is None
    finally:
        release.set()
        toggle.join(5)
    assert services.session_playback()[0] == session
    # A second toggle at the same time as none: the same session stops.
    services.toggle_session_playback(session)
    assert services.session_playback() is None


async def test_a_delete_stops_the_player_of_that_session_and_leaving_does_not(
    tmp_path, monkeypatch
):
    players: list[FakePlayer] = []

    def start_player(command):
        players.append(FakePlayer())
        return players[-1]

    app, services, _clock, session = _player_app(tmp_path, monkeypatch, start_player)
    try:
        async with app.run_test(size=(120, 35)) as pilot:
            await _open(pilot, app, 1)
            await pilot.press("p")
            await _until(pilot, lambda: services.session_playback() is not None, "no player")
            await pilot.press("1")
            await pilot.pause(0.1)
            assert not players[0].terminated, "leaving the Library stopped the player"
            await pilot.press("2", "delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.press("y")
            await _until(pilot, lambda: not (tmp_path / "sessions" / session).exists())
            assert players[0].terminated, "the deleted session still plays"
            assert services.session_playback() is None
    finally:
        services.stop_session_playback()


async def test_show_library_clears_a_kept_search_and_opens_the_session(tmp_path):
    root, sessions = _library(tmp_path)
    SessionStore(root).set_title(sessions["file"], "Zebra crossing survey")
    app = make_app(tmp_path, FakeServices(root))
    screen = app.library_screen
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 4)
        await pilot.press("slash", *"zebra", "enter")
        await _until(pilot, lambda: [e.entry_id for e in screen.entries] == [sessions["file"]])
        await pilot.press("enter", "1")
        await pilot.pause()

        app.show_library(sessions["live"])
        await _until(pilot, lambda: screen.opened and screen.selected_id == sessions["live"])
        assert screen.search_query == ""
        assert not app.screen.query_one("#library-search", Input).display
        assert _button(app, "library-search-button").label.plain == "[/] search"
        assert not any("was not found" in notice for notice in _notices(app))

        # A session saved after the list was read.
        newer = _write_rec(root, REC_LIVE + timedelta(days=3)).name
        await pilot.press("1")
        app.show_library(newer)
        await _until(pilot, lambda: screen.opened and screen.selected_id == newer)


def _meta(app) -> str:
    return app.screen.query_one("#library-session-meta", Static).render().plain


async def test_the_open_session_shows_the_state_word_of_the_wide_table(tmp_path):
    root, sessions = _library(tmp_path)
    services = FakeServices(root)
    services.jobs.append(FakeJob("file-1", tmp_path / "sources" / "standup.flac", state="queued"))
    app = make_app(tmp_path, services)
    screen = app.library_screen
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(screen.entries) == 5)
        await pilot.press("enter")
        await _settle(pilot, app)
        head = _meta(app)
        assert head.count("queued") == 1, head
        assert head.split(" · ")[0].strip() == "transcribe", head

        await pilot.press("escape")
        screen.select_entry(sessions["file"])
        await pilot.press("enter")
        await _until(
            pilot, lambda: screen.detail is not None and screen._detail_id == sessions["file"]
        )
        await _settle(pilot, app)
        head = _meta(app)
        # A file session whose speaker pass ran has live labels: the state slot says so.
        assert head.split(" · ")[0].strip() == "live", head


class _HeldPlayAudio:
    """A play preparation that waits until the test releases it."""

    def __init__(self, path):
        self.path = path
        self.preparing = threading.Event()
        self.release = threading.Event()

    def write_play_audio(self, session_id):
        self.preparing.set()
        assert self.release.wait(5), "the test did not release the preparation"
        self.path.write_bytes(b"")
        return self.path


async def test_a_delete_during_the_play_preparation_stops_that_player(tmp_path, monkeypatch):
    players: list[FakePlayer] = []

    def start_player(command):
        players.append(FakePlayer())
        return players[-1]

    app, services, _clock, session = _player_app(tmp_path, monkeypatch, start_player)
    held = _HeldPlayAudio(tmp_path / "play.wav")
    services._session_jobs = held
    try:
        async with app.run_test(size=(120, 35)) as pilot:
            await _open(pilot, app, 1)
            await pilot.press("p")
            await asyncio.to_thread(held.preparing.wait, 5)
            await pilot.press("delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.press("y")
            await pilot.pause(0.1)
            # The delete waits for the preparation; the session is still there.
            assert (tmp_path / "sessions" / session).exists()
            held.release.set()
            await _until(pilot, lambda: not (tmp_path / "sessions" / session).exists())
            assert len(players) == 1 and players[0].terminated
            assert services.session_playback() is None
    finally:
        held.release.set()
        services.stop_session_playback()


async def test_a_delete_of_another_session_leaves_the_player_alone(tmp_path, monkeypatch):
    players: list[FakePlayer] = []

    def start_player(command):
        players.append(FakePlayer())
        return players[-1]

    app, services, _clock, playing = _player_app(tmp_path, monkeypatch, start_player)
    other = _write_rec(tmp_path / "sessions", REC_LIVE - timedelta(days=1)).name
    try:
        async with app.run_test(size=(120, 35)) as pilot:
            await _open(pilot, app, 2)
            await pilot.press("p")
            await _until(pilot, lambda: services.session_playback() is not None)
            assert services.session_playback()[0] == playing
            app.library_screen.select_entry(other)
            await pilot.press("delete")
            await _until(pilot, lambda: isinstance(app.screen, QuitConfirm))
            await pilot.press("y")
            await _until(pilot, lambda: not (tmp_path / "sessions" / other).exists())
            assert not players[0].terminated
            assert services.session_playback()[0] == playing
    finally:
        services.stop_session_playback()


def test_an_ended_player_is_not_reported_while_the_next_play_is_prepared(tmp_path, monkeypatch):
    _app, services, _clock, session = _player_app(tmp_path, monkeypatch, lambda c: FakePlayer())
    ended = FakePlayer()
    ended.finished.set()
    # The player ended, and its watcher has not run yet.
    services._player = ended
    services._player_session_id = "20261001T000000Z"
    services._playing = ("20261001T000000Z", 0.0)
    held = _HeldPlayAudio(tmp_path / "play.wav")
    services._session_jobs = held
    toggle = threading.Thread(target=services.toggle_session_playback, args=(session,))
    toggle.start()
    try:
        assert held.preparing.wait(5)
        assert services.session_playback() is None
    finally:
        held.release.set()
        toggle.join(5)
    assert services.session_playback()[0] == session
    services.stop_session_playback()


async def test_a_file_transcribe_revision_shows_re_transcribe_in_both_views(tmp_path):
    root = tmp_path / "sessions"
    session = _write_rec(root, REC_LIVE).name
    store = SessionStore(root)
    detail = store.read(session)
    store.write_revision(
        session, detail.lines, method="file-transcribe", expected_revision=detail.revision
    )
    app = make_app(tmp_path, FakeServices(root))
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot, app, 1)
        row = _line_of(app, f"{REC_LIVE.astimezone():%d %b %H:%M}")
        assert row.rstrip(" │").endswith("re-transcribe"), row
        assert "file-transcri" not in _screen_text(app)
        width = len(row)
        await pilot.press("enter")
        await _settle(pilot, app)
        head = _meta(app)
        assert head.split(" · ")[0].strip() == "re-transcribe", head
        assert len(_line_of(app, "[esc] ← Library")) == width


# Transcript position

SIZES = pytest.mark.parametrize("size", [(120, 35), (60, 16)])


def _long_lines(prefix: str, count: int = 60) -> tuple[TranscriptLine, ...]:
    return tuple(
        TranscriptLine(i, i + 1, "", "system", "speaker-1", "Speaker 1", f"{prefix}{i:03d}")
        for i in range(count)
    )


def _write_long_rec(tmp_path, started_at, prefix: str) -> str:
    writer = SessionWriter.open(tmp_path, started_at)
    for line in _long_lines(prefix):
        writer.append_line(line)
    writer.close()
    return writer.path.name


def _shows(app, text: str) -> bool:
    return text in _screen_text(app)


async def _open_entry(pilot, app, entry_id: str) -> None:
    screen = app.library_screen
    screen.select_entry(entry_id)
    # One user path: the table has loaded the detail of the selected entry before enter.
    if screen.selected_entry.summary is not None:
        await _until(pilot, lambda: screen.detail is not None and screen._detail_id == entry_id)
    await pilot.press("enter")
    await _settle(pilot, app)


@SIZES
async def test_a_saved_session_opens_at_its_first_line_and_so_does_the_next_one(tmp_path, size):
    first = _write_long_rec(tmp_path, REC_LIVE, "alpha")
    second = _write_long_rec(tmp_path, REC_LIVE - timedelta(days=1), "bravo")
    app = make_app(tmp_path, FakeServices(tmp_path / "sessions"))
    async with app.run_test(size=size) as pilot:
        await _open(pilot, app, 2)
        await _open_entry(pilot, app, first)
        transcript = app.screen.query_one("#library-transcript")
        assert transcript.max_scroll_y > 3, "the transcript must be longer than its view"
        assert _shows(app, "alpha000")
        assert not _shows(app, "alpha059")
        assert _layout_problems(app) == []

        await pilot.press("down", "down", "down")
        assert transcript.scroll_y == 3
        await pilot.press("escape")
        await _settle(pilot, app)
        # The same session opens again at its first line.
        await _open_entry(pilot, app, first)
        assert _shows(app, "alpha000")
        assert not _shows(app, "alpha059")

        await pilot.press("down", "down", "down")
        assert transcript.scroll_y == 3
        await pilot.press("escape")
        await _settle(pilot, app)
        await _open_entry(pilot, app, second)
        assert _shows(app, "bravo000")
        assert not _shows(app, "bravo059")
        assert _layout_problems(app) == []

        # Home, end and the line keys act as before.
        await pilot.press("end")
        assert transcript.scroll_y == transcript.max_scroll_y
        assert _shows(app, "bravo059")
        await pilot.press("home", "down")
        assert transcript.scroll_y == 1


@SIZES
async def test_a_redraw_of_the_open_session_keeps_the_scroll_position(tmp_path, size):
    session = _write_long_rec(tmp_path, REC_LIVE, "alpha")
    root = tmp_path / "sessions"
    services = FakeServices(root)
    services.release_job.set()
    app = make_app(tmp_path, services)
    screen = app.library_screen
    async with app.run_test(size=size) as pilot:
        await _open(pilot, app, 1)
        await _open_entry(pilot, app, session)
        transcript = app.screen.query_one("#library-transcript")
        await pilot.press("down", "down", "down")
        assert transcript.scroll_y == 3

        SessionStore(root).set_title(session, TITLE)
        screen.load_sessions()
        await _until(pilot, lambda: screen.selected_entry.summary.title == TITLE)
        await _settle(pilot, app)
        assert transcript.scroll_y == 3

        revision = screen.detail.revision
        await pilot.press("d")
        await _until(
            pilot, lambda: screen.detail is not None and screen.detail.revision != revision
        )
        await _settle(pilot, app)
        assert ("diarization", session) in services.actions
        assert transcript.scroll_y == 3
        assert _shows(app, "alpha003")
        assert _layout_problems(app) == []


@SIZES
async def test_a_running_file_job_follows_its_newest_line(tmp_path, size):
    session = _write_long_rec(tmp_path, REC_LIVE, "alpha")
    services = FakeServices(tmp_path / "sessions")
    job = FakeJob("file-1", tmp_path / "sources" / "lecture.mp3", percent=40)
    job.progress = FileJobProgress("transcribe", 40, _long_lines("juliet", 40))
    services.jobs.append(job)
    app = make_app(tmp_path, services)
    screen = app.library_screen
    async with app.run_test(size=size) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(screen.entries) == 2)
        # A saved session viewed at its first line does not stop the job from following.
        await _open_entry(pilot, app, session)
        await pilot.press("home", "escape")
        await _settle(pilot, app)
        await _open_entry(pilot, app, "job:file-1")
        assert _shows(app, "juliet039")
        assert not _shows(app, "juliet000")

        job.progress = FileJobProgress("transcribe", 80, _long_lines("juliet", 80))
        screen.poll_jobs()
        await _settle(pilot, app)
        assert _shows(app, "juliet079")
        assert _layout_problems(app) == []


@SIZES
async def test_a_file_job_that_finishes_while_open_keeps_the_scroll_position(tmp_path, size):
    root = tmp_path / "sessions"
    services = FakeServices(root)
    source = tmp_path / "sources" / "lecture.wav"
    job = FakeJob("file-1", source, percent=90)
    lines = _long_lines("juliet")
    job.progress = FileJobProgress("transcribe", 90, lines)
    services.jobs.append(job)
    app = make_app(tmp_path, services)
    screen = app.library_screen
    async with app.run_test(size=size) as pilot:
        await pilot.press("2")
        await _until(pilot, lambda: len(screen.entries) == 1)
        await _open_entry(pilot, app, "job:file-1")
        transcript = app.screen.query_one("#library-transcript")
        await pilot.press("up", "up", "up")
        position = transcript.scroll_y
        assert 0 < position == transcript.max_scroll_y - 3

        source.parent.mkdir(parents=True)
        sf.write(source, np.zeros(16_000, dtype=np.float32), 16_000)
        job.session_id = SessionStore(root).create_file_session(
            source, started_at=REC_LIVE, duration_seconds=60.0, lines=lines
        )
        job.state = "completed"
        await _until(
            pilot,
            lambda: screen.selected_id == job.session_id and screen.detail is not None,
        )
        await _settle(pilot, app)
        assert screen.opened
        assert transcript.scroll_y == position
        assert _layout_problems(app) == []


class _Gate:
    """Hold each call of a store method until the test opens the gate."""

    def __init__(self, method):
        self.method = method
        self.open = threading.Event()
        self.open.set()
        self.waiting = threading.Event()

    def __call__(self, *args):
        self.waiting.set()
        if not self.open.wait(timeout=5):
            raise TimeoutError("test gate was not opened")
        return self.method(*args)


@SIZES
async def test_enter_before_the_detail_loads_opens_at_the_first_line(tmp_path, size):
    session = _write_long_rec(tmp_path, REC_LIVE, "alpha")
    services = FakeServices(tmp_path / "sessions")
    store = services.session_store
    detail_gate = store.read = _Gate(store.read)
    detail_gate.open.clear()
    app = make_app(tmp_path, services)
    screen = app.library_screen
    try:
        async with app.run_test(size=size) as pilot:
            await pilot.press("2")
            await _until(pilot, lambda: len(screen.entries) == 1)
            await _until(pilot, detail_gate.waiting.is_set)
            await pilot.press("enter")
            await _settle(pilot, app)
            assert screen.opened and screen.detail is None
            assert _shows(app, "Loading…")

            detail_gate.open.set()
            await _until(pilot, lambda: screen.detail is not None and screen._detail_id == session)
            await _settle(pilot, app)
            assert _shows(app, "alpha000")
            assert not _shows(app, "alpha059")
            assert _layout_problems(app) == []
    finally:
        detail_gate.open.set()


async def test_another_session_opened_before_a_finished_job_is_listed_shows_no_wrong_lines(
    tmp_path,
):
    root = tmp_path / "sessions"
    other = _write_long_rec(tmp_path, REC_LIVE, "bravo")
    services = FakeServices(root)
    store = services.session_store
    source = tmp_path / "sources" / "sierra.wav"
    job = FakeJob("file-1", source, percent=90)
    job.progress = FileJobProgress("transcribe", 90, _long_lines("juliet"))
    services.jobs.append(job)
    app = make_app(tmp_path, services)
    screen = app.library_screen
    list_gate = detail_gate = None
    try:
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("2")
            await _until(pilot, lambda: len(screen.entries) == 2)
            await _open_entry(pilot, app, "job:file-1")
            assert _shows(app, "juliet059")

            source.parent.mkdir(parents=True)
            sf.write(source, np.zeros(16_000, dtype=np.float32), 16_000)
            finished = store.create_file_session(
                source, started_at=REC_LIVE, duration_seconds=60.0, lines=_long_lines("sierra")
            )
            list_gate = store.list_sessions = _Gate(store.list_sessions)
            list_gate.open.clear()
            job.session_id = finished
            job.state = "completed"
            # The list read that lists the finished session waits at the gate.
            await _until(pilot, list_gate.waiting.is_set)

            await pilot.press("escape")
            await _settle(pilot, app)
            await _open_entry(pilot, app, other)
            assert _shows(app, "bravo000")

            detail_gate = store.read = _Gate(store.read)
            detail_gate.open.clear()
            list_gate.open.set()
            await _until(pilot, lambda: screen.selected_id == finished)
            await _until(pilot, detail_gate.waiting.is_set)
            await _settle(pilot, app)
            # The head shows the finished session; no line of the other session shows under it.
            assert "sierra.wav" in _line_of(app, "[e] Edit title…")
            assert not _shows(app, "bravo")
            assert _shows(app, "Loading…")

            detail_gate.open.set()
            await _until(pilot, lambda: screen.detail is not None and screen._detail_id == finished)
            await _settle(pilot, app)
            assert _shows(app, "sierra000")
            assert not _shows(app, "sierra059")
            assert _layout_problems(app) == []
    finally:
        for gate in (list_gate, detail_gate):
            if gate is not None:
                gate.open.set()
