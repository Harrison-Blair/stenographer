# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library layout at each size: no cut or overlap, the rows that must show, resizes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from textual.widgets import Input

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.library_table import title_width
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.title_dialog import TitleDialog
from stenographer.cli.hub.transcribe_dialog import TranscribeDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.speaker_bar import SpeakerBar
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions import SessionStore
from tests.cli.hub.support import _layout_problems, _screen_text, make_app
from tests.cli.hub.test_library import FakeJob, FakeServices, _library, _until

pytestmark = pytest.mark.usefixtures("utc")

SIZES = ((150, 45), (120, 35), (100, 30), (80, 24), (80, 20), (60, 16), (150, 16), (120, 16))
TEXT = "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima"
LONG_NAME = "A speaker name of forty-five characters long!"
NAMES = (LONG_NAME, *(f"Speaker {number}" for number in range(1, 12)))
LONG_TITLE = ("A title of two hundred characters " + "that keeps going and going " * 7)[:200]
LONG_FILE = "an-eighty-character-file-name-" + "x" * 46 + ".wav"
ACTIONS = (
    "library-play",
    "library-rename",
    "library-rediarize",
    "library-retranscribe",
    "library-export",
    "library-delete",
)


def _write_session(tmp_path, hour: int, names=NAMES) -> str:
    writer = SessionWriter.open(tmp_path, datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=hour))
    for index in range(40):
        name = names[index % len(names)]
        writer.append_line(
            TranscriptLine(index * 6.0, index * 6.0 + 5, "", "mic", f"id-{name}", name, TEXT)
        )
    writer.close()
    return writer.path.name


def _sessions(tmp_path, count: int) -> FakeServices:
    root = tmp_path / "sessions"
    for hour in range(count):
        _write_session(tmp_path, hour)
    store = SessionStore(root)
    if count:
        newest = store.list_sessions()[0].session_id
        store.set_title(newest, LONG_TITLE)
    return FakeServices(root)


def _row_states(tmp_path) -> FakeServices:
    """The row states of sessions and file jobs (``Library-rows``)."""
    root, _sessions = _library(tmp_path)
    services = FakeServices(root)
    sources = tmp_path / "sources"
    services.jobs.extend(
        (
            FakeJob("file-1", sources / "standup.flac", state="queued", percent=0),
            FakeJob("file-2", sources / LONG_FILE, state="running", percent=100),
            FakeJob("file-3", sources / "damaged.wav", state="failed"),
        )
    )
    services.jobs[2].error = "needs ffmpeg"
    return services


async def _show_table(pilot, app, count: int) -> None:
    await pilot.press("2")
    await _until(pilot, lambda: app.library_screen.entry_count == count, "list did not load")
    library = app.library_screen
    if count and library.selected_entry.summary is not None:
        await _until(pilot, lambda: library.detail is not None, "no detail")
    await _settle(pilot, app)


async def _settle(pilot, app) -> None:
    app.refresh_view()
    await pilot.pause()
    await pilot.pause()
    await pilot.pause()


def _shown(app, selector: str) -> bool:
    widget = app.screen.query_one(selector)
    return bool(widget.display and widget.region.area)


def _assert_table(app, count: int) -> None:
    for selector in ("#library-search-row", "#library-columns", "#library-list"):
        assert _shown(app, selector), selector
    assert _shown(app, "#library-transcribe") and _shown(app, "#library-count")
    # At least four entries of two lines each show from 60x16.
    rows = app.screen.query_one("#library-list-scroll").content_region.height
    assert rows >= 2 * min(4, count), rows


def _assert_session(app) -> None:
    for selector in (
        "#library-back",
        "#library-session-meta",
        "#library-detail-title",
        "#library-title-button",
        "#library-play",
    ):
        assert _shown(app, selector), selector
    assert app.screen.query_one("#library-transcript").region.height >= 6
    width, height = app.size
    bar = app.screen.query_one("#library-speakers", SpeakerBar)
    lines = len(bar.bar_text(bar.size.width).plain.splitlines())
    assert lines <= (1 if height < 28 or width < 80 else 2), lines
    _assert_buttons_fit(app)
    _assert_title_row(app)


def _assert_title_row(app) -> None:
    """Both title buttons from 80 columns, else only ``[e] Title…``; a cut title ends with ``…``."""
    edit = app.screen.query_one("#library-title-button", HubButton)
    generate = app.screen.query_one("#library-generate-button", HubButton)
    row = _screen_text(app).splitlines()[edit.region.y]
    if app.size.width >= 80:
        assert generate.display and generate.region.area
        assert "[e] Edit title…  [g] Generate title" in row, row
    else:
        assert not generate.display
        assert "[e] Title…" in row and "[g]" not in row, row
    title = app.screen.query_one("#library-detail-title")
    shown = row[title.region.x : title.region.right].rstrip()
    library = app.library_screen
    full = library.selected_entry.summary
    if full is not None and full.session_id in library._generating:
        assert shown == "generating…", shown
    elif full is not None and full.title is not None and len(full.title) > title.region.width:
        assert shown.endswith("…") and full.title.startswith(shown[:-1].rstrip()), shown


def _assert_buttons_fit(app) -> None:
    """Hide a button only when it does not fit; show every button from 80 columns."""
    buttons = [app.screen.query_one(f"#{button_id}", HubButton) for button_id in ACTIONS]
    shown = [button for button in buttons if button.display]
    assert shown == buttons[: len(shown)], "the shown buttons are the first ones"
    if app.size.width >= 80:
        assert len(shown) == len(buttons)
        return
    grid = app.screen.query_one("#library-actions")
    if len(shown) < len(buttons):
        # One row with a gap of 3 cells between buttons (Session-60 board).
        labels = [button.label.cell_length for button in buttons[: len(shown) + 1]]
        assert sum(labels) + 3 * len(shown) > grid.content_size.width


TABLES = {
    "empty": (lambda tmp_path: _sessions(tmp_path, 0), 0),
    "one": (lambda tmp_path: _sessions(tmp_path, 1), 1),
    "twelve": (lambda tmp_path: _sessions(tmp_path, 12), 12),
    "rows": (_row_states, 7),
}


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize("case", list(TABLES))
async def test_the_table_fits_every_size(tmp_path, case, size):
    make_services, count = TABLES[case]
    app = make_app(tmp_path, make_services(tmp_path))
    async with app.run_test(size=size) as pilot:
        await _show_table(pilot, app, count)
        assert _layout_problems(app) == []
        _assert_table(app, count)
        if not count:
            assert "No saved sessions." in _screen_text(app)
        # Scroll to the end: rows below the view must fit too.
        await pilot.press("end")
        await _settle(pilot, app)
        assert _layout_problems(app) == []


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize("query", ["golf", "xylophone"])
async def test_the_search_fits_every_size(tmp_path, query, size):
    app = make_app(tmp_path, _sessions(tmp_path, 3))
    async with app.run_test(size=size) as pilot:
        await _show_table(pilot, app, 3)
        await pilot.press("slash", *query)
        expected = 3 if query == "golf" else 0
        await _until(pilot, lambda: len(app.library_screen.entries) == expected)
        await _settle(pilot, app)
        assert _layout_problems(app) == []
        assert (
            query
            in _screen_text(app).splitlines()[app.screen.query_one("#library-search-row").region.y]
        )
        if not expected:
            assert "No matches." in _screen_text(app)
        hints = app.screen.query_one("#key-hints").render().plain
        assert "? help" not in hints and "q quit" not in hints


def _busy(app):
    library = app.library_screen
    app.try_acquire_session(library.selected_id, "test")
    library._session_work[library.selected_id] = "re-transcribe"


def _playing(app):
    library = app.library_screen
    app.services.session_playback = lambda: (library.selected_id, 99.0)


def _generating(app):
    library = app.library_screen
    app.services.title_request.release.clear()
    assert app.services.titles.generate(library.selected_id)
    library._generating = app.services.titles.generating


SESSIONS = {
    "live": (lambda tmp_path: _sessions(tmp_path, 2), 2, 0, None),
    "generating": (lambda tmp_path: _sessions(tmp_path, 2), 2, 0, _generating),
    "file": (_row_states, 7, 5, None),
    "job": (_row_states, 7, 1, None),
    "busy": (lambda tmp_path: _sessions(tmp_path, 2), 2, 0, _busy),
    "playing": (lambda tmp_path: _sessions(tmp_path, 2), 2, 0, _playing),
}


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize("case", list(SESSIONS))
async def test_the_open_session_fits_every_size(tmp_path, case, size):
    make_services, count, index, change = SESSIONS[case]
    app = make_app(tmp_path, make_services(tmp_path))
    async with app.run_test(size=size) as pilot:
        await _show_table(pilot, app, count)
        library = app.library_screen
        library.select_entry(library.entries[index].entry_id)
        if change is not None:
            change(app)
        await pilot.press("enter")
        await _settle(pilot, app)
        assert _layout_problems(app) == []
        _assert_session(app)
        if case == "playing" and size[0] >= 80:
            assert "■ Stop 00:01:39 / " in app.screen.query_one("#library-play").label.plain
        await pilot.press("end")
        await _settle(pilot, app)
        assert _layout_problems(app) == []
        app.services.title_request.release.set()


async def _open_title(pilot, app):
    await pilot.press("e")
    return TitleDialog


async def _open_rename(pilot, app):
    await pilot.press("r")
    return RenameDialog


async def _open_export(pilot, app):
    await pilot.press("x")
    return ExportDialog


async def _open_delete(pilot, app):
    await pilot.press("delete")
    return QuitConfirm


async def _open_transcribe(pilot, app):
    await pilot.press("n")
    return TranscribeDialog


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize(
    "open_dialog", [_open_title, _open_rename, _open_export, _open_delete, _open_transcribe]
)
async def test_each_dialog_fits_every_size(tmp_path, open_dialog, size):
    services = _sessions(tmp_path, 2)
    app = make_app(tmp_path, services, files_home=tmp_path)
    async with app.run_test(size=size) as pilot:
        await _show_table(pilot, app, 2)
        dialog = await open_dialog(pilot, app)
        await _until(pilot, lambda: isinstance(app.screen, dialog), "no dialog")
        await pilot.pause()
        assert _layout_problems(app) == []


@pytest.mark.parametrize("opened", [False, True], ids=["table", "session"])
async def test_below_the_floor_the_library_shows_the_size_line(tmp_path, opened):
    app = make_app(tmp_path, _sessions(tmp_path, 2))
    async with app.run_test(size=(120, 35)) as pilot:
        await _show_table(pilot, app, 2)
        if opened:
            await pilot.press("enter")
        await pilot.resize_terminal(59, 15)
        await _settle(pilot, app)
        times = "\N{MULTIPLICATION SIGN}"
        assert _screen_text(app).strip() == f"60{times}16 needed · now  59{times}15"
        await pilot.resize_terminal(120, 35)
        await _settle(pilot, app)
        assert app.library_screen.opened == opened
        assert _layout_problems(app) == []


HISTORIES = (
    ((150, 45), (60, 16), (150, 45)),
    ((60, 16), (120, 35), (80, 20)),
    ((150, 16), (80, 24), (150, 16)),
)


@pytest.mark.parametrize("history", HISTORIES, ids=lambda h: "-".join(f"{w}x{r}" for w, r in h))
async def test_resize_histories_fit_the_table_and_the_open_session(tmp_path, history):
    app = make_app(tmp_path, _sessions(tmp_path, 12))
    async with app.run_test(size=history[0]) as pilot:
        await _show_table(pilot, app, 12)
        oldest = f"{app.library_screen.entries[-1].summary.started_at:%d %b %H:%M}"
        for size in history[1:]:
            # The last entry is selected: after the resize its row must still show.
            await pilot.press("end")
            await _settle(pilot, app)
            await pilot.resize_terminal(*size)
            await _settle(pilot, app)
            assert _layout_problems(app) == [], ("table", size)
            _assert_table(app, 12)
            assert any(
                line.lstrip("│ ").startswith(f"▶ {oldest}")
                for line in _screen_text(app).splitlines()
            ), ("the selected row is out of view", size)
            await pilot.press("home")
            await _settle(pilot, app)
            heading = _screen_text(app).splitlines()[
                app.screen.query_one("#library-columns").region.y
            ]
            row = next(line for line in _screen_text(app).splitlines() if "A title of" in line)
            assert "▶" in row
            # The first line of the selected entry holds the start of the long title.
            assert heading.index("title") == row.index("A title of"), size
            if size[0] >= 120:
                # The columns after the title line up too: the heading leaves the scrollbar.
                assert heading.index("state") == row.index("! interrupted"), size
        await pilot.press("enter")
        for size in reversed(history):
            await pilot.resize_terminal(*size)
            await _settle(pilot, app)
            assert _layout_problems(app) == [], ("session", size)
            _assert_session(app)


async def test_an_open_search_keeps_its_text_and_cursor_through_tier_changes(tmp_path):
    app = make_app(tmp_path, _sessions(tmp_path, 2))
    async with app.run_test(size=(120, 35)) as pilot:
        await _show_table(pilot, app, 2)
        await pilot.press("slash", *"golf", "left", "left")
        search = app.screen.query_one("#library-search", Input)
        for size in ((60, 16), (90, 24), (120, 35)):
            await pilot.resize_terminal(*size)
            await _settle(pilot, app)
            assert (search.value, search.cursor_position, search.has_focus) == ("golf", 2, True)


async def test_the_title_dialog_keeps_its_text_and_selection_through_tier_changes(tmp_path):
    app = make_app(tmp_path, _sessions(tmp_path, 2))
    async with app.run_test(size=(120, 35)) as pilot:
        await _show_table(pilot, app, 2)
        await pilot.press("e")
        await _until(pilot, lambda: isinstance(app.screen, TitleDialog))
        field = app.screen.query_one("#title-input", Input)
        field.value = "Budget review"
        field.selection = (0, 6)
        for size in ((60, 16), (90, 24), (150, 45)):
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert field.value == "Budget review"
            assert tuple(field.selection) == (0, 6)
            assert _layout_problems(app) == []


def _title_slice(app) -> slice:
    table = app.screen.query_one("#library-list")
    heading = _screen_text(app).splitlines()[app.screen.query_one("#library-columns").region.y]
    start = heading.index("title")
    return slice(start, start + title_width(app.library_screen.tier, table.size.width))


def _without(line: str, cells: slice) -> str:
    return line[: cells.start] + line[cells.stop :]


@pytest.mark.parametrize("size", SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
async def test_generating_moves_no_column_and_no_button(tmp_path, size):
    services = _sessions(tmp_path, 2)
    services.title_request.release.clear()
    app = make_app(tmp_path, services)
    async with app.run_test(size=size) as pilot:
        await _show_table(pilot, app, 2)
        library = app.library_screen
        # The second entry has no title: "—" or its speakers, then "generating…".
        library.select_entry(library.entries[1].entry_id)
        await _settle(pilot, app)
        y = app.screen.query_one("#library-list").region.y + 2
        cells = _title_slice(app)
        before = _screen_text(app).splitlines()[y : y + 2]
        await pilot.press("g")
        await _until(pilot, lambda: services.title_request.started.is_set())
        await _until(pilot, lambda: "generating…" in _screen_text(app), "no generating…")
        await _settle(pilot, app)
        during = _screen_text(app).splitlines()[y : y + 2]
        assert during[0][cells].rstrip() == "generating…"
        assert [_without(line, cells) for line in during] == [
            _without(line, cells) for line in before
        ]
        assert _layout_problems(app) == []

        await pilot.press("enter")
        await _settle(pilot, app)
        ids = (
            "#library-title-button",
            "#library-generate-button",
            "#library-speakers",
            *(f"#{button_id}" for button_id in ACTIONS),
        )
        generating = {selector: app.screen.query_one(selector).region for selector in ids}
        title = app.screen.query_one("#library-detail-title")
        assert title.render().plain == "generating…"
        services.title_request.release.set()
        await _until(pilot, lambda: not services.titles.generating, "still generating")
        await _until(pilot, lambda: "A generated title" in _screen_text(app), "no title")
        await _settle(pilot, app)
        assert {selector: app.screen.query_one(selector).region for selector in ids} == generating
        assert _layout_problems(app) == []
        _assert_session(app)
