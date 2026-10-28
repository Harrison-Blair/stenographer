# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the shared hub widgets, the button actions and the help overlay."""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from rich.color import Color
from rich.console import Console
from textual.app import App
from textual.binding import Binding
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.help_overlay import HelpOverlay
from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.cli.hub.widgets.status_token import StatusToken
from stenographer.cli.shared.no_background_css import NO_BACKGROUND_CSS
from stenographer.lib.config.defaults import default_toml


class IdleServices:
    recording = False
    files_running = False
    session = None


class WidgetApp(App[None]):
    CSS = NO_BACKGROUND_CSS + HubButton.APP_CSS
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [("x", "export", "Export")]

    def __init__(self, *widgets):
        super().__init__()
        self._widgets = widgets
        self.exports = 0

    def compose(self):
        yield from self._widgets

    def action_export(self) -> None:
        self.exports += 1


def _accent(style) -> bool:
    return style.bold and style.color.get_truecolor() == Color.parse("#5fd7ff").get_truecolor()


def test_widget_button_prints_its_key_and_never_wraps():
    async def exercise():
        button = HubButton("Export the whole session", key="x", action="export", id="export")
        app = WidgetApp(button)
        async with app.run_test(size=(16, 5)) as pilot:
            await pilot.pause()
            assert str(button.label) == "[x] Export the whole session"
            assert button.region.height == 1
            assert not button.can_focus

    asyncio.run(exercise())


def test_widget_button_click_runs_the_action_of_its_key():
    async def exercise():
        app = WidgetApp(HubButton("Export", key="x", action="export", id="export"))
        async with app.run_test() as pilot:
            await pilot.press("x")
            assert app.exports == 1
            await pilot.click("#export")
            await pilot.pause()
            assert app.exports == 2

    asyncio.run(exercise())


def test_widget_settings_tab_click_matches_the_tab_keys(tmp_path):
    async def exercise():
        path = tmp_path / "config.toml"
        path.write_text(default_toml(), encoding="utf-8")
        app = HubApp(IdleServices(), config_path=path)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "right", "right")
            by_keys = (app.settings_screen.tab, app.config_editor.visible_keys)
            await pilot.click("#tab-general")
            await pilot.pause()
            assert app.settings_screen.tab == "general"
            await pilot.click("#tab-recognition")
            await pilot.pause()
            assert (app.settings_screen.tab, app.config_editor.visible_keys) == by_keys

    asyncio.run(exercise())


def test_widget_checks_buttons_run_the_same_actions_as_their_keys():
    async def exercise():
        probes = []
        report = DoctorReport(
            (DoctorCheck("has_mic", "microphone", "input and audio", "warn", "", ""),), ()
        )
        app = HubApp(
            IdleServices(),
            doctor_probe=lambda _config, _path: probes.append("probe") or report,
            open_log=lambda _path: probes.append("log") or True,
        )
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "left")
            await pilot.pause(0.1)
            assert probes == ["probe"]
            await pilot.press("r")
            await pilot.pause(0.1)
            assert probes == ["probe", "probe"]
            buttons = {str(b.label): b for b in app.screen.query(HubButton)}
            await pilot.click(buttons["[r] Run again"])
            await pilot.pause(0.1)
            assert probes == ["probe", "probe", "probe"]
            await pilot.click(buttons["[l] Open log"])
            await pilot.pause()
            assert probes[-1] == "log"

    asyncio.run(exercise())


def test_widget_selectable_list_rows_are_one_line_with_a_bold_accent_marker():
    async def exercise():
        rows = SelectableList(id="rows")
        app = WidgetApp(rows)
        async with app.run_test(size=(20, 6)) as pilot:
            await pilot.pause()
            rows.set_rows(
                (("alpha bravo charlie delta", "12"), ("echo", "")),
                selected_index=0,
            )
            await pilot.pause()
            text = rows.render()
            lines = text.plain.splitlines()
            assert len(lines) == 2
            assert lines[0].startswith("▶ alpha")
            assert "…" in lines[0] and lines[0].endswith("12")
            assert lines[1] == "  echo"
            assert _accent(text.get_style_at_offset(0).rich_style)
            assert rows.region.height == 2

            await pilot.click("#rows", offset=(3, 1))
            assert rows.selected_index == 1

    asyncio.run(exercise())


def test_widget_status_token_is_a_glyph_and_a_word():
    assert StatusToken.text("●", "recording", "danger").plain == "● recording"
    with pytest.raises(ValueError):
        StatusToken.text("", "recording")
    with pytest.raises(ValueError):
        StatusToken.text("●", " ")


def test_widget_footer_key_hints_end_with_help_and_quit():
    async def exercise():
        hints = KeyHints(id="hints")
        app = WidgetApp(hints)
        async with app.run_test(size=(60, 3)) as pilot:
            await pilot.pause()
            hints.set_hints(("n", "new"), ("q", "quit"))
            text = hints.render()
            assert text.plain == "n new · ? help · q quit"
            assert _accent(text.get_style_at_offset(0).rich_style)
            assert _accent(text.get_style_at_offset(text.plain.index("?")).rich_style)

    asyncio.run(exercise())


@pytest.mark.parametrize("screen", ["record", "library", "settings"])
def test_help_overlay_lists_every_active_binding_and_closes(screen):
    async def exercise():
        app = HubApp(IdleServices())
        async with app.run_test(size=(150, 45)) as pilot:
            app.show_screen(screen)
            await pilot.pause()
            hints = str(app.screen.query_one("#key-hints", Static).render())
            assert hints.endswith("? help · q quit")
            active = app.screen.active_bindings
            shown = [(key, item.binding) for key, item in active.items() if item.binding.show]
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpOverlay)
            rows = app.screen.rows
            assert len(rows) == len(shown)
            descriptions = [description for _key, description in rows]
            for _key, binding in shown:
                assert binding.description in descriptions
            await pilot.press("escape")
            assert not isinstance(app.screen, HelpOverlay)
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
            await pilot.press("question_mark")
            assert not isinstance(app.screen, HelpOverlay)

    asyncio.run(exercise())


def test_help_every_hub_binding_has_a_help_row():
    from stenographer.cli.hub.checks_tab import ChecksTab
    from stenographer.cli.hub.library_screen import LibraryScreen
    from stenographer.cli.hub.record_screen import RecordScreen
    from stenographer.cli.hub.settings_screen import SettingsScreen

    missing = []
    for owner in (HubApp, RecordScreen, LibraryScreen, SettingsScreen, ChecksTab):
        for binding in owner.BINDINGS:
            binding = binding if isinstance(binding, Binding) else Binding(*binding)
            if binding.show and not binding.description.strip():
                missing.append(f"{owner.__name__}: {binding.key}")
    assert missing == []


def test_help_rows_name_keys_and_skip_hidden_bindings():
    async def exercise():
        app = HubApp(IdleServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            rows = dict(HelpOverlay.help_rows(app.screen.active_bindings))
            assert rows["space"] == "Record, pause or resume"
            assert rows["?"] == "Help for this screen"
            assert rows["1"] == "Record screen"
            assert "tab" not in rows and "ctrl+p" not in rows

    asyncio.run(exercise())


def _plain_rows(app: App) -> list[str]:
    """Return the plain text of each composited row: no colour, no style."""
    return [strip.text for strip in app.screen._compositor.render_strips()]


def test_widget_field_marks_the_focused_row_with_a_glyph():
    from stenographer.cli.hub.widgets.field import Field

    def plain(field: Field) -> str:
        return "".join(segment.text for segment in Console().render(field.row())).rstrip()

    rows = {
        (focused, changed): plain(Field("Model", "qwen3:4b", changed=changed, focused=focused))
        for focused in (False, True)
        for changed in (False, True)
    }
    assert rows[(True, False)].startswith("▶  Model")
    assert rows[(True, True)].startswith("▶● Model")
    assert rows[(False, True)].startswith(" ● Model")
    assert rows[(False, False)].startswith("   Model")


@pytest.mark.parametrize("dialog", ["quit", "config"])
def test_widget_dialog_marks_the_focused_button_with_a_glyph(dialog):
    from stenographer.cli.hub.config_dialog import ConfigPrompt
    from stenographer.cli.hub.dialogs import QuitConfirm

    async def exercise():
        app = WidgetApp()
        async with app.run_test(size=(100, 30)) as pilot:
            if dialog == "quit":
                app.push_screen(QuitConfirm("Quit now?", confirm="Quit", cancel="Stay"))
                labels = ("[n] Stay", "[y] Quit")
            else:
                choices = (("Save", "save"), ("Discard", "discard"), ("Stay", "stay"))
                app.push_screen(ConfigPrompt("Unsaved?", choices=choices))
                labels = ("[s] Save", "[d] Discard", "[esc] Stay")
            await pilot.pause()
            text = "\n".join(_plain_rows(app))
            focused = app.focused.label.plain.strip().removeprefix("▶").strip()
            assert text.count("▶") == 1, text
            assert f"▶ {focused}" in text, text
            await pilot.press("tab")
            await pilot.pause()
            text = "\n".join(_plain_rows(app))
            moved = app.focused.label.plain.strip().removeprefix("▶").strip()
            assert moved != focused
            assert text.count("▶") == 1, text
            assert f"▶ {moved}" in text, text
            assert {focused, moved} <= set(labels)

    asyncio.run(exercise())
