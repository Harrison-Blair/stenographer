# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify transparent backgrounds and selected-row styles in both TUIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

from rich.color import Color
from rich.text import Text
from textual.widgets import OptionList, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
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


def _painted_backgrounds(app, label: str, errors: list[str]) -> None:
    for row, strip in enumerate(app.screen._compositor.render_strips()):
        column = 0
        for segment in strip._segments:
            if segment.style is not None and segment.style.reverse:
                widget, _region = app.screen._compositor.get_widget_at(column, row)
                errors.append(
                    f"{label}, row {row}: {segment.text!r} uses reverse style in "
                    f"{type(widget).__name__}#{widget.id}"
                )
            column += segment.cell_length
            background = segment.style.bgcolor if segment.style is not None else None
            if background is not None and not background.is_default:
                errors.append(f"{label}, row {row}: {segment.text!r} has {background!r}")


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
            _painted_backgrounds(app, "Live idle", errors)

            services.session = FakeSession()
            services.recording = True
            app._refresh_view()
            await pilot.pause()
            _painted_backgrounds(app, "Live recording", errors)
            await pilot.press("v")
            _painted_backgrounds(app, "Live split", errors)

            for key, label in (("2", "Files"), ("3", "Sessions"), ("4", "Config"), ("5", "Setup")):
                await pilot.press(key)
                await pilot.pause()
                _painted_backgrounds(app, label, errors)

            await pilot.press("6")
            await pilot.pause()
            app._doctor_report = report
            app._doctor_index = 0
            app._refresh_view()
            _painted_backgrounds(app, "Doctor", errors)

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
            speaker_options = app.screen.query_one(OptionList)
            prompt = speaker_options.get_option_at_index(1).prompt
            assert isinstance(prompt, Text)
            assert "▶ Speaker 1" in prompt.plain
            assert prompt.spans[0].style == "bold #5fd7ff"
            await pilot.press("escape")

        live_app = LiveApp(FakeSession())
        async with live_app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            _painted_backgrounds(live_app, "stenographer live", errors)

        assert not errors, "\n".join(errors)

    asyncio.run(exercise())


def test_selected_sidebar_and_file_rows_use_bold_accent_marker(tmp_path):
    async def exercise():
        (tmp_path / "sample.wav").touch()
        app = HubApp(FakeServices(), files_home=tmp_path)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar", Static).render()
            _assert_selected_row(sidebar, "▶ 1 Live")

            await pilot.press("2")
            file_rows = app.query_one("#files-browser", Static).render()
            _assert_selected_row(file_rows, "▶ [ ] sample.wav")

    asyncio.run(exercise())
