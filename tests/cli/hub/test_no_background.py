# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify transparent backgrounds and selected-row styles in both TUIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from rich.color import Color
from rich.text import Text
from textual.scrollbar import ScrollBar
from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
from stenographer.cli.hub.files_view import FilesPanel
from stenographer.cli.hub.widgets.help_overlay import HelpOverlay
from stenographer.cli.live.app import LiveApp
from stenographer.cli.live.rename_dialog import RenameDialog
from stenographer.lib.config.defaults import default_toml


class FakeSession:
    paused = False
    lines = ()
    speakers = (("speaker-1", "Speaker 1"),)
    source_states: ClassVar[dict[str, str]] = {"mic": "on", "system": "on"}
    source_reasons: ClassVar[dict[str, str | None]] = {"mic": None, "system": None}
    levels_dbfs: ClassVar[dict[str, float]] = {"mic": -24.0, "system": -18.0}
    meter_floor_dbfs = -70.0
    failed_phrase_count = 0
    elapsed_seconds = 12.0
    queue_depth = 0
    relabel_progress = None
    idle_unload_deadline = None
    model_name = "medium.en · int8"
    relabel_status = ""
    relabel_error = None
    path = Path("/tmp/session")

    def subscribe(self, _callback):
        pass

    def start(self):
        pass


class FakeServices:
    recording = False
    files_running = False
    session = None


def _plain(renderable) -> str:
    return renderable.plain if isinstance(renderable, Text) else renderable


def _painted_backgrounds(app, label: str, errors: list[str]) -> int:
    scrollbar_thumb_cells = 0
    for row, strip in enumerate(app.screen._compositor.render_strips()):
        column = 0
        for segment in strip._segments:
            widget, _region = app.screen._compositor.get_widget_at(column, row)
            style = segment.style
            # Textual renders full-cell scrollbar thumbs with reverse segments.
            is_scrollbar_thumb = bool(style and style.reverse) and all(
                isinstance(app.screen._compositor.get_widget_at(column + offset, row)[0], ScrollBar)
                for offset in range(segment.cell_length)
            )
            if style is not None and style.reverse:
                if is_scrollbar_thumb:
                    scrollbar_thumb_cells += segment.cell_length
                else:
                    errors.append(
                        f"{label}, row {row}: {segment.text!r} uses reverse style in "
                        f"{type(widget).__name__}#{widget.id}"
                    )
            background = style.bgcolor if style is not None else None
            if background is not None and not background.is_default and not is_scrollbar_thumb:
                errors.append(f"{label}, row {row}: {segment.text!r} has {background!r}")
            column += segment.cell_length
    return scrollbar_thumb_cells


def _assert_selected_row(renderable, expected: str) -> None:
    assert expected in renderable.plain
    offset = renderable.plain.index("▶")
    style = next(span.style for span in renderable.spans if span.start <= offset < span.end)
    rich_style = style.rich_style
    assert rich_style.bold
    assert rich_style.color is not None
    assert rich_style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
    assert rich_style.bgcolor is None or rich_style.bgcolor.is_default


def test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds(tmp_path):
    async def exercise():
        (tmp_path / "sample.wav").touch()
        config_path = tmp_path / "config.toml"
        config_path.write_text(default_toml(), encoding="utf-8")
        report = DoctorReport(
            (
                DoctorCheck(
                    "mic", "microphone", "input and audio", "warn", "Unavailable", "Connect one."
                ),
            ),
            (),
        )
        services = FakeServices()
        app = HubApp(
            services,
            config_path=config_path,
            files_home=tmp_path,
            doctor_probe=lambda _config, _path: report,
        )
        errors = []

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            _painted_backgrounds(app, "Record idle", errors)

            services.session = FakeSession()
            services.recording = True
            app.refresh_view()
            await pilot.pause()
            _painted_backgrounds(app, "Record recording", errors)
            await pilot.press("v")
            _painted_backgrounds(app, "Record split", errors)

            await pilot.press("2")
            await pilot.pause()
            _painted_backgrounds(app, "Library", errors)
            await pilot.press("n")
            await pilot.pause()
            _painted_backgrounds(app, "Library files", errors)
            await pilot.press("escape")

            await pilot.press("3")
            await pilot.pause()
            for tab in ("general", "audio", "recognition", "live", "checks"):
                app.settings_screen.select_tab(tab)
                await pilot.pause()
                _painted_backgrounds(app, f"Settings {tab}", errors)

            app.push_screen(HelpOverlay("Settings", app.screen.active_bindings))
            await pilot.pause()
            _painted_backgrounds(app, "Help overlay", errors)
            await pilot.press("escape")

            app.push_screen(QuitConfirm("Stop recording?"))
            await pilot.pause()
            _painted_backgrounds(app, "Quit dialog", errors)
            await pilot.press("escape")

            app.push_screen(ConfigPrompt("Edit a value", initial="value"))
            await pilot.pause()
            _painted_backgrounds(app, "Config dialog", errors)
            await pilot.press("escape")

            app.push_screen(RenameDialog(FakeSession.speakers))
            await pilot.pause()
            _painted_backgrounds(app, "Speaker dialog", errors)
            select = app.screen.query_one("#speaker-select")
            select.focus()
            await pilot.press("enter", "down")
            await pilot.pause()
            _painted_backgrounds(app, "Speaker picker", errors)
            await pilot.press("escape")

        live_app = LiveApp(FakeSession())
        async with live_app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            _painted_backgrounds(live_app, "stenographer live", errors)

        assert not errors, "\n".join(errors)

    asyncio.run(exercise())


def test_files_directory_rows_keep_base_alignment(tmp_path):
    (tmp_path / "sample.wav").touch()
    files = FilesPanel(home=tmp_path)
    assert "       ../" in _plain(files._render_browser()).splitlines()


def test_files_queue_error_lines_keep_two_cell_indent(tmp_path):
    files = FilesPanel(home=tmp_path)
    files.jobs = (
        SimpleNamespace(
            options=SimpleNamespace(path=tmp_path / "sample.wav"), error="Decode failed"
        ),
    )
    assert "  Decode failed" in _plain(files._render_queue()).splitlines()


def test_blank_input_cursor_is_accent_underlined_without_a_fill():
    app = HubApp(FakeServices())

    async def exercise():
        async with app.run_test(size=(120, 36)) as pilot:
            app.push_screen(RenameDialog(FakeSession.speakers))
            await pilot.pause()
            input_widget = app.screen.query_one("#speaker-name", Input)
            input_widget.focus()
            await pilot.pause()
            cursor_segments = [
                segment
                for segment in input_widget.render_line(0)._segments
                if segment.style is not None and segment.style.underline
            ]
            assert cursor_segments
            for segment in cursor_segments:
                assert segment.style.color is not None
                assert segment.style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()
                assert segment.style.bgcolor is None or segment.style.bgcolor.is_default
                assert not segment.style.reverse

    asyncio.run(exercise())


def test_visible_scrollbar_thumb_is_the_only_background_exception(tmp_path):
    for index in range(50):
        (tmp_path / f"{index:02}.wav").touch()
    app = HubApp(FakeServices(), files_home=tmp_path)
    errors = []

    async def exercise():
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("2", "n")
            await pilot.pause()
            thumb_cells = _painted_backgrounds(app, "Files scrolling", errors)
            assert thumb_cells > 0

    asyncio.run(exercise())
    assert not errors, "\n".join(errors)


def test_selected_sidebar_and_file_rows_use_bold_accent_marker(tmp_path):
    async def exercise():
        (tmp_path / "sample.wav").touch()
        app = HubApp(FakeServices(), files_home=tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one("#sidebar", Static).render()
            _assert_selected_row(sidebar, "▶ 1 Record")

            await pilot.press("2", "n")
            file_rows = app.screen.query_one("#files-browser", Static).render()
            _assert_selected_row(file_rows, "▶ [ ] sample.wav")

    asyncio.run(exercise())
