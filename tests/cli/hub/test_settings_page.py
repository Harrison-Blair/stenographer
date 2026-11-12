# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the one-page Settings tab: groups, columns, message line and fixed slots."""

from __future__ import annotations

import pytest
from textual.containers import ScrollableContainer
from textual.widgets import Button, Input

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.widgets.field import Field
from stenographer.lib.config.defaults import default_toml
from tests.cli.hub.support import _config_path, _fields

FAIL = "\N{MULTIPLICATION SIGN}"
PAGE = (
    ("KEYS", ("Agent key", "General key", "Cancel key", "Hotkey mode")),
    ("AUDIO", ("Microphone", "Volume", "Sound pack", "Overlay")),
    ("TEXT", ("Vocabulary", "Copy original", "Restore clipboard")),
    ("REFINE", ("Refine", "Host", "Model")),
    ("RECORDING", ("Separate room speakers", "Meter floor dBFS")),
    ("SYSTEM", ("Usage history", "Idle unload")),
)
SIZES = [(150, 45), (120, 35), (100, 30), (80, 24), (60, 16)]
SHIFTED = default_toml().replace('binding = "KEY_RIGHTCTRL"', 'binding = "KEY_RIGHTSHIFT"', 1)


class IdleServices:
    recording = False
    files_running = False
    session = None

    def update_config(self, config):
        self.config = config


def _app(tmp_path, content=None):
    app = HubApp(IdleServices(), config_editor=ConfigEditor(_config_path(tmp_path, content)))
    app.settings_screen.list_devices = lambda _key: []
    return app


def _lines(app) -> list[str]:
    return [strip.text for strip in app.screen._compositor.render_strips()]


def _find(app, text: str) -> tuple[int, int]:
    """Return (row, column) of the first screen cell that starts ``text``."""
    for row, line in enumerate(_lines(app)):
        if text in line:
            return row, line.index(text)
    raise AssertionError(f"{text!r} is not on screen")


def _message(app) -> str:
    return app.settings_screen.query_one("#config-summary").render().plain


async def _open(pilot):
    await pilot.press("3")
    await pilot.pause()


async def test_settings_is_one_page_of_six_groups_beside_a_checks_tab(tmp_path):
    app = _app(tmp_path)
    async with app.run_test(size=(150, 45)) as pilot:
        await _open(pilot)
        labels = [field.label for field in _fields(app)]
        assert labels == [label for _group, rows in PAGE for label in rows]
        text = "\n".join(_lines(app))
        for group, _rows in PAGE:
            assert group in text
        assert "▶ Settings" in text and "Checks" in text
        for retired in ("General", "Recognition", "Live", "Audio"):
            assert retired not in text.split("\n")[2], retired


@pytest.mark.parametrize(("size", "columns"), [((150, 45), 2), ((120, 35), 2), ((100, 30), 1)])
async def test_settings_shows_two_columns_only_when_wide(tmp_path, size, columns):
    app = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await _open(pilot)
        keys_row, keys_col = _find(app, "KEYS")
        refine_row, refine_col = _find(app, "REFINE")
        if columns == 2:
            assert refine_row == keys_row and refine_col > keys_col
        else:
            assert refine_col == keys_col and refine_row > keys_row


@pytest.mark.parametrize(("size", "gap"), [((100, 30), 1), ((60, 16), 0)])
async def test_settings_leaves_a_line_between_groups_except_when_narrow(tmp_path, size, gap):
    app = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await _open(pilot)
        screen = app.settings_screen
        last_key_row = next(f for f in _fields(app) if f.label == "Hotkey mode")
        audio = screen.query_one(".group-audio")
        assert audio.virtual_region.y == last_key_row.virtual_region.bottom + gap


@pytest.mark.parametrize("size", [(150, 45), (120, 35)])
async def test_wide_save_button_keeps_its_place_while_the_count_grows(tmp_path, size):
    app = _app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await _open(pilot)
        editor = app.config_editor
        editor.set_value("feedback.volume", 0.2)
        app.refresh_view()
        await pilot.pause()
        save = _find(app, "[ctrl+s] Save")
        discard = _find(app, "Discard all")
        editor.set_value("feedback.overlay", False)
        app.refresh_view()
        await pilot.pause()
        assert _find(app, "[ctrl+s] Save") == save
        assert _find(app, "Discard all") == discard
        row = _lines(app)[save[0]]
        assert row[save[1] :].split("Save", 1)[1].strip().startswith("2 changes")


async def test_medium_tab_row_has_no_count_and_the_message_line_has_it(tmp_path):
    app = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await _open(pilot)
        app.config_editor.set_value("feedback.overlay", False)
        app.refresh_view()
        await pilot.pause()
        row, _col = _find(app, "[ctrl+s] Save")
        assert "change" not in _lines(app)[row]
        assert "● 1 unsaved change" in _message(app)
        assert _message(app).startswith("config.toml · ")


async def test_narrow_message_line_drops_the_file_name(tmp_path):
    app = _app(tmp_path)
    async with app.run_test(size=(60, 16)) as pilot:
        await _open(pilot)
        assert _message(app).startswith("0 unsaved changes")


async def test_message_line_shows_the_default_of_the_selected_row_not_the_row(tmp_path):
    app = _app(tmp_path, SHIFTED)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot)
        assert "default KEY_RIGHTCTRL" in _message(app)
        row, _col = _find(app, "Agent key")
        assert "default" not in _lines(app)[row]
        await pilot.press("down")
        await pilot.pause()
        assert "default" not in _message(app)
        assert "backups none yet" in _message(app)


async def test_message_line_shows_a_refused_input_and_the_row_does_not(tmp_path):
    app = _app(tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        await _open(pilot)
        app.settings_screen.open_setting("refine.model")
        await pilot.pause()
        await pilot.press("enter", "ctrl+a", "ctrl+k", "enter")
        await pilot.pause()
        assert isinstance(app.screen.focused, Input), "the input stays open"
        assert f"{FAIL} Model must be non-empty" in _message(app)
        row = next(line for line in _lines(app) if "Model" in line and "config.toml" not in line)
        assert FAIL not in row
        await pilot.press("escape")
        await pilot.pause()
        assert FAIL not in _message(app)


def _layout_problems(app) -> list[str]:
    """Each shown widget outside the screen or its parent, each overlap, each cut label."""
    screen = app.screen
    problems = []
    shown = []
    for widget in screen.query("*"):
        region = widget.region
        if not widget.display or not region.area:
            continue
        name = widget.id or type(widget).__name__
        if isinstance(widget, Field) and len(widget.label) > widget.LABEL_WIDTH:
            problems.append(f"{name} cuts its label: {widget.label}")
        if isinstance(widget, Button) and widget.label.cell_length > widget.content_size.width:
            problems.append(f"{name} cuts its label: {widget.label}")
        if any(isinstance(node, ScrollableContainer) for node in widget.ancestors):
            continue
        if not screen.region.contains_region(region):
            problems.append(f"{name} leaves the screen: {region}")
        parent = widget.parent
        if parent is not screen and not parent.content_region.contains_region(region):
            problems.append(f"{name} leaves {parent.id}: {region}")
        shown.append((widget, region))
    for index, (widget, region) in enumerate(shown):
        for other, other_region in shown[index + 1 :]:
            related = widget in other.ancestors or other in widget.ancestors
            if not related and region.overlaps(other_region):
                problems.append(f"{widget.id or widget} overlaps {other.id or other}")
    return problems


@pytest.mark.parametrize("size", SIZES)
async def test_settings_page_has_no_cut_or_overlapping_widget(tmp_path, size):
    app = _app(tmp_path, SHIFTED)
    async with app.run_test(size=size) as pilot:
        await _open(pilot)
        app.config_editor.set_value("feedback.overlay", False)
        app.refresh_view()
        await pilot.pause()
        assert _layout_problems(app) == []
        app.settings_screen.open_setting("refine.host")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert _layout_problems(app) == []
