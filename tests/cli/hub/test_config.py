# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration editing behavior in the hub."""

from __future__ import annotations

import asyncio

from rich.color import Color
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.widgets.field import Field
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config
from tests.cli.hub.support import _config_path, _fields


class FakeServices:
    recording = False
    files_running = False

    def update_config(self, config):
        self.config = config


async def _edit_idle_unload(pilot, value):
    await pilot.press("3", "/")
    await pilot.press(*tuple("asr.idle_unload_seconds"), "enter", "enter")
    await pilot.press("ctrl+a", "ctrl+k", *tuple(value), "enter")


def _field(app, label):
    return next(field for field in _fields(app) if field.label == label)


def _focused(app) -> Field:
    return next(field for field in _fields(app) if field.focused)


def _notification_messages(app):
    return [notification.message for notification in app._notifications]


async def test_settings_page_shows_values_and_rows_move(tmp_path):
    app = HubApp(FakeServices(), config_editor=ConfigEditor(_config_path(tmp_path)))
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        focused = _focused(app)
        assert app.settings_screen.tab == "settings"
        assert focused.label == "Agent key"
        assert focused.control.plain == "KEY_RIGHTCTRL"
        assert app.screen.query_one("#tab-settings").label.plain.startswith("▶")

        await pilot.press("down")
        assert app.config_editor.selected_key == "hotkey.general_binding"
        assert _focused(app).label == "General key"
        await pilot.press("up", "up")
        assert app.config_editor.selected_key == "asr.idle_unload_seconds"


def test_config_settings_use_one_compact_label_value_row_per_key(tmp_path):
    content = default_toml().replace("idle_unload_seconds = 900", "idle_unload_seconds = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_editor=ConfigEditor(_config_path(tmp_path, content)))
        async with app.run_test(size=(100, 45)) as pilot:
            await pilot.press("3")
            app.settings_screen.open_setting("analytics.enabled")
            await pilot.pause()
            rows = [strip.text for strip in app.screen._compositor.render_strips()]
            usage = next(row for row in rows if "Usage history" in row)
            idle = next(row for row in rows if "Idle unload" in row)
            assert "▶  Usage history" in usage and "(●) on" in usage
            assert "▶" not in idle and " 5 s" in idle and "default" not in idle
            assert "Default:" not in "\n".join(rows)
            assert usage.index("Usage history") == idle.index("Idle unload")

    asyncio.run(exercise())


async def test_config_focused_row_is_bold_accent_and_unsaved_change_has_warn_dot(tmp_path):
    app = HubApp(FakeServices(), config_editor=ConfigEditor(_config_path(tmp_path)))
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.press("3")
        app.settings_screen.open_setting("asr.idle_unload_seconds")
        await pilot.press("enter", "ctrl+a", "ctrl+k", "5")
        await pilot.press("enter")
        await pilot.pause()
        row = _field(app, "Idle unload")
        assert row.focused and row.changed
        rendered = app.screen._compositor.render_strips()
        line = next(strip for strip in rendered if "Idle unload" in strip.text)
        assert "▶● Idle unload" in line.text
        styles = {segment.text: segment.style for segment in line if segment.text.strip()}
        label = next(style for text, style in styles.items() if "Idle unload" in text)
        assert label.bold and label.color == Color.parse("#5fd7ff")
        assert label.bgcolor is None or label.bgcolor.is_default
        dot = next(style for text, style in styles.items() if "●" in text)
        assert dot.color == Color.parse("#ffaf5f")


async def test_config_message_shows_the_default_only_when_the_selected_value_differs(tmp_path):
    app = HubApp(FakeServices(), config_editor=ConfigEditor(_config_path(tmp_path)))
    async with app.run_test(size=(150, 45)) as pilot:
        await pilot.press("3")
        app.settings_screen.open_setting("asr.idle_unload_seconds")
        await pilot.pause()
        summary = app.screen.query_one("#config-summary", Static)
        assert "default" not in summary.render().plain
        app.config_editor.edit("asr.idle_unload_seconds", "60")
        app.refresh_view()
        assert "default 900" in summary.render().plain
        assert _field(app, "Idle unload").note == ""
        app.config_editor.undo()
        app.refresh_view()
        assert "default" not in summary.render().plain


async def test_config_summary_shows_path_and_unsaved_change_count(tmp_path):
    path = _config_path(tmp_path)
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await pilot.press("3")
        summary = app.screen.query_one("#config-summary", Static)
        assert "config.toml" in summary.render().plain
        assert "0 unsaved changes" in summary.render().plain

        app.config_editor.edit("asr.idle_unload_seconds", "60")
        app.config_editor.edit("feedback.volume", "0.3")
        app.refresh_view()
        assert "2 unsaved changes" in summary.render().plain
        rendered = summary.render()
        count_offset = rendered.plain.index("2 unsaved changes")
        count_style = rendered.get_style_at_offset(count_offset).rich_style
        assert count_style.color == Color.parse("#ffaf5f")

        app.config_editor.undo()
        app.refresh_view()
        assert "1 unsaved change" in summary.render().plain


async def test_edit_undo_and_reset_use_validated_config_values(tmp_path):
    path = _config_path(tmp_path)
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await _edit_idle_unload(pilot, "3")
        assert app.config_editor.config.asr.idle_unload_seconds == 3
        await _edit_idle_unload(pilot, "5")
        assert app.config_editor.config.asr.idle_unload_seconds == 5

        await pilot.press("u")
        assert app.config_editor.config.asr.idle_unload_seconds == 3
        await pilot.press("shift+d")
        assert (
            app.config_editor.config.asr.idle_unload_seconds
            == Config.defaults().asr.idle_unload_seconds
        )
        assert not app.config_editor.dirty
        assert (
            Config.load(path).asr.idle_unload_seconds == Config.defaults().asr.idle_unload_seconds
        )


async def test_config_live_group_edits_and_saves_mic_diarization(tmp_path):
    path = _config_path(tmp_path)
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await pilot.press("3", "/")
        await pilot.press(*tuple("live.diarize_mic"), "enter")
        await pilot.pause()
        assert app.config_editor.selected_key == "live.diarize_mic"
        await pilot.press("enter")
        assert app.config_editor.config.live.diarize_mic is True
        await pilot.press("ctrl+s")
        assert Config.load(path).live.diarize_mic is True


async def test_invalid_edit_is_rejected_by_config_validation(tmp_path):
    app = HubApp(FakeServices(), config_editor=ConfigEditor(_config_path(tmp_path)))
    async with app.run_test() as pilot:
        await _edit_idle_unload(pilot, "-1")
        assert (
            app.config_editor.config.asr.idle_unload_seconds
            == Config.defaults().asr.idle_unload_seconds
        )
        assert not app.config_editor.dirty
        assert any("asr.idle_unload_seconds" in message for message in _notification_messages(app))


async def test_conflict_keeps_external_config_and_unsaved_draft(tmp_path):
    path = _config_path(tmp_path)
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await _edit_idle_unload(pilot, "5")
        external = path.read_bytes() + b"\n# external edit\n"
        path.write_bytes(external)
        await pilot.press("ctrl+s")
        assert path.read_bytes() == external
        assert app.config_editor.config.asr.idle_unload_seconds == 5
        assert app.config_editor.dirty
        assert any(
            "changed while setup was running" in message for message in _notification_messages(app)
        )


async def test_invalid_config_is_read_only_and_shows_error_and_fix_path(tmp_path):
    path = _config_path(tmp_path, "[stenographer.asr]\nidle_unload_seconds = -1\n")
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await pilot.press("3", "enter", "ctrl+s")
        await pilot.pause()
        content = str(app.screen.query_one("#config-message", Static).render())
        assert app.config_editor.read_only
        assert not app.screen.query_one("#config-save").display
        assert "read-only" in content
        assert str(path) in content
        assert "asr.idle_unload_seconds" in content
        assert path.read_text(encoding="utf-8") == "[stenographer.asr]\nidle_unload_seconds = -1\n"


async def test_search_selects_a_key_and_unsaved_navigation_asks_for_discard(tmp_path):
    path = _config_path(tmp_path)
    app = HubApp(FakeServices(), config_editor=ConfigEditor(path))
    async with app.run_test() as pilot:
        await pilot.press("3", "/")
        await pilot.press(*tuple("asr.idle_unload_seconds"), "enter")
        assert app.config_editor.selected_key == "asr.idle_unload_seconds"
        await pilot.press("enter")
        await pilot.press("ctrl+a", "ctrl+k", "5", "enter")
        await pilot.press("2")
        assert (
            "unsaved configuration changes"
            in str(app.screen.query_one("#config-prompt-message", Static).render()).lower()
        )
        await pilot.click("#choice-discard")
        assert app.current_mode == "library"
        assert not app.config_editor.dirty
        assert (
            Config.load(path).asr.idle_unload_seconds == Config.defaults().asr.idle_unload_seconds
        )
