# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Settings tabs: Field rows, the unsaved model and keys."""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Input

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.widgets.field import Field
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config


class IdleServices:
    recording = False
    files_running = False
    session = None

    def update_config(self, config):
        self.config = config


TAB_KEYS = {
    "general": (
        "hotkey.binding",
        "hotkey.device",
        "hotkey.cancel_binding",
        "hotkey.mode",
        "hotkey.hybrid_threshold_seconds",
        "hotkey.general_binding",
        "feedback.volume",
        "feedback.mute",
        "feedback.overlay",
        "feedback.sound_pack",
        "feedback.update_check",
        "feedback.log_level",
        "delivery.copy_original",
        "delivery.restore_clipboard",
        "delivery.restore_delay_ms",
        "analytics.enabled",
        "analytics.resource_profiling",
    ),
    "audio": (
        "audio.input_device",
        "audio.min_speech_rms",
        "audio.max_recording_seconds",
        "feedback.spectrum_floor_dbfs",
    ),
    "recognition": (
        "asr.idle_unload_seconds",
        "asr.cpu_threads",
        "refine.vocabulary",
        "refine.enabled",
        "refine.host",
        "refine.model",
        "refine.min_words",
        "refine.structured_output",
    ),
    "live": ("live.diarize_mic",),
}


def _config_path(tmp_path, content=None):
    path = tmp_path / "config.toml"
    path.write_text(default_toml() if content is None else content, encoding="utf-8")
    return path


def _app(tmp_path, content=None, devices=None):
    app = HubApp(IdleServices(), config_path=_config_path(tmp_path, content))
    app.settings_screen.list_devices = lambda _key: list(devices or ())
    return app


def _fields(app) -> list[Field]:
    return list(app.settings_screen.query("#config-rows Field").results(Field))


def _field(app, label: str) -> Field:
    return next(field for field in _fields(app) if field.label == label)


def _plain(field: Field) -> str:
    control = field.control
    return control if isinstance(control, str) else control.plain


def _screen_text(app) -> str:
    """Return the composited screen as plain text: no colour, no style."""
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


def _messages(app) -> list[str]:
    return [notification.message for notification in app._notifications]


async def _open(pilot, tab="general"):
    await pilot.press("3")
    pilot.app.settings_screen.select_tab(tab)
    await pilot.pause()


async def _select(pilot, label):
    app = pilot.app
    for _ in range(len(_fields(app))):
        if _field(app, label).focused:
            return
        await pilot.press("down")
        await pilot.pause()
    raise AssertionError(f"no row {label}")


def test_settings_each_key_sits_in_its_tab_as_one_field_row(tmp_path):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot)
            every_key = set(app.config_editor.all_keys)
            seen = set()
            for tab, keys in TAB_KEYS.items():
                app.settings_screen.select_tab(tab)
                await pilot.pause()
                assert app.config_editor.visible_keys == keys
                assert len(_fields(app)) == len(keys)
                seen.update(keys)
            assert seen == every_key

            app.settings_screen.select_tab("recognition")
            await pilot.pause()
            labels = [field.label for field in _fields(app)]
            assert labels == [
                "Idle unload",
                "CPU threads",
                "Vocabulary",
                "Refine",
                "Host",
                "Model",
                "Minimum words",
                "Structured output",
            ]
            text = _screen_text(app)
            assert "▶ Recognition" in text
            assert "applies to new sessions and jobs" in text

    asyncio.run(exercise())


def test_settings_rows_draw_the_control_that_fits_the_key(tmp_path):
    assert Config.defaults().refine.structured_output is False

    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            assert _plain(_field(app, "Idle unload")).strip() == "900 s"
            assert _plain(_field(app, "Refine")) == "(●) on"
            assert _plain(_field(app, "Structured output")) == "( ) off"
            assert _plain(_field(app, "Vocabulary")) == "[enter] Edit list… 0 terms"
            assert _plain(_field(app, "Model")) == Config.defaults().refine.model
            app.settings_screen.select_tab("general")
            await pilot.pause()
            assert _plain(_field(app, "Hotkey mode")) == "hybrid ▾"
            assert _plain(_field(app, "Log level")) == "info ▾"
            app.settings_screen.select_tab("audio")
            await pilot.pause()
            assert _plain(_field(app, "Microphone")) == "Default input ▾"
            assert "local text cleanup" not in _field(app, "Microphone").help_text

    asyncio.run(exercise())


def test_settings_number_row_rejects_letters_and_marks_the_unsaved_change(tmp_path):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            assert not any(field.changed for field in _fields(app))
            await pilot.press("enter")
            await pilot.pause()
            editor_input = app.screen.focused
            assert isinstance(editor_input, Input)
            await pilot.press("ctrl+a", "ctrl+k", "x", "6", "y", "0")
            assert editor_input.value == "60"
            await pilot.press("enter")
            await pilot.pause()
            assert app.config_editor.config.asr.idle_unload_seconds == 60
            assert not app.screen.query(Input)
            row = _field(app, "Idle unload")
            assert row.changed and _plain(row).strip() == "60 s"
            assert "● 1 unsaved change" in _screen_text(app)
            assert "[ctrl+s] Save 1 change" in _screen_text(app)

    asyncio.run(exercise())


def test_settings_dot_marks_a_change_from_the_saved_file_not_the_default(tmp_path):
    content = default_toml().replace("cpu_threads = 0", "cpu_threads = 5")

    async def exercise():
        app = _app(tmp_path, content)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            row = _field(app, "CPU threads")
            assert not row.changed
            assert "●" not in _screen_text(app).split("CPU threads")[0].splitlines()[-1]
            await pilot.press("down", "shift+d")
            await pilot.pause()
            assert app.config_editor.config.asr.cpu_threads == 0
            assert _field(app, "CPU threads").changed
            await pilot.press("u")
            await pilot.pause()
            assert app.config_editor.config.asr.cpu_threads == 5
            assert not _field(app, "CPU threads").changed

    asyncio.run(exercise())


def test_settings_space_toggles_and_undo_reset_and_discard_all(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(IdleServices(), config_path=path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            await _select(pilot, "Refine")
            await pilot.press("space")
            await pilot.pause()
            assert app.config_editor.config.refine.enabled is False
            assert _plain(_field(app, "Refine")) == "( ) off"
            await pilot.press("down", "down", "down", "down", "space")
            await pilot.pause()
            assert app.config_editor.unsaved_change_count == 2
            await pilot.press("u")
            assert app.config_editor.unsaved_change_count == 1
            await _select(pilot, "Refine")
            await pilot.press("shift+d")
            await pilot.pause()
            assert app.config_editor.config.refine.enabled is True
            assert not app.config_editor.dirty

            await pilot.press("space")
            await pilot.click("#config-discard")
            await pilot.pause()
            assert "Discard 1 unsaved change?" in _screen_text(app)
            await pilot.press("n")
            await pilot.pause()
            assert app.config_editor.dirty
            await pilot.click("#config-discard")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert not app.config_editor.dirty
            assert app.config_editor.config.refine.enabled is True
            assert Config.load(path) == app.config_editor.config

    asyncio.run(exercise())


def test_settings_choice_and_device_rows_open_their_lists(tmp_path):
    devices = [("3", "3: USB microphone"), ("5", "5: Desk array")]

    async def exercise():
        app = _app(tmp_path, devices=devices)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot)
            await _select(pilot, "Hotkey mode")
            await pilot.press("enter")
            await pilot.pause()
            text = _screen_text(app)
            for mode in ("hold", "toggle", "▶ hybrid"):
                assert mode in text
            await pilot.press("up", "enter")
            await pilot.pause()
            assert app.config_editor.config.hotkey.mode == "toggle"
            assert _field(app, "Hotkey mode").changed

            app.settings_screen.select_tab("audio")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            text = _screen_text(app)
            assert "▶ Default input" in text and "5: Desk array" in text
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert app.config_editor.config.audio.input_device == "5"
            assert _plain(_field(app, "Microphone")) == "5: Desk array ▾"

            await pilot.press("enter", "escape")
            await pilot.pause()
            assert app.config_editor.config.audio.input_device == "5"

    asyncio.run(exercise())


def test_settings_save_keeps_a_backup_and_a_comment(tmp_path):
    content = "# my note about threads\n" + default_toml()

    async def exercise():
        path = _config_path(tmp_path, content)
        app = HubApp(IdleServices(), config_path=path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            assert "backups\nnone yet" in app.screen.query_one("#sidebar-card").render().plain
            await pilot.press("down", "enter", "ctrl+a", "ctrl+k", "3", "enter")
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert Config.load(path).asr.cpu_threads == 3
            assert path.read_text(encoding="utf-8").startswith("# my note about threads\n")
            backups = list(tmp_path.glob("config.toml.bak-*"))
            assert len(backups) == 1
            assert backups[0].read_text(encoding="utf-8") == content
            assert not _field(app, "CPU threads").changed
            card = app.screen.query_one("#sidebar-card").render().plain
            assert "0 unsaved changes" in card
            assert f"backups\n{backups[0].name}\nlast " in card
            assert "[ctrl+s] Save 0 changes" in _screen_text(app)

    asyncio.run(exercise())


def test_settings_ctrl_s_saves_the_value_typed_in_the_row(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(IdleServices(), config_path=path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            await pilot.press("enter", "ctrl+a", "ctrl+k", "7", "5", "ctrl+s")
            await pilot.pause()
            assert Config.load(path).asr.idle_unload_seconds == 75

    asyncio.run(exercise())


def test_settings_letters_go_to_a_focused_text_input(tmp_path):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot, "recognition")
            await _select(pilot, "Model")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+a", "ctrl+k", *"Du/1q", "space", "x")
            await pilot.pause()
            assert app.screen.focused.value == "Du/1q x"
            assert app.current_mode == "settings" and app.is_running
            assert app.settings_screen.tab == "recognition"
            assert not app.config_editor.dirty
            await pilot.press("escape")
            await pilot.pause()
            assert not app.screen.query(Input)
            assert not app.config_editor.dirty
            await pilot.press("enter", "ctrl+a", "ctrl+k", *"small", "enter")
            await pilot.pause()
            assert app.config_editor.config.refine.model == "small"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("key", "tab", "label"),
    [
        ("hotkey.mode", "general", "Hotkey mode"),
        ("audio.min_speech_rms", "audio", "Minimum speech level"),
        ("refine.model", "recognition", "Model"),
        ("live.diarize_mic", "live", "Separate room speakers"),
    ],
)
def test_settings_open_setting_selects_the_row_on_each_tab(tmp_path, key, tab, label):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            app.config_editor.edit("hotkey.binding", "KEY_F9")
            app.open_setting(key)
            await pilot.pause()
            assert app.settings_screen.tab == tab
            assert app.config_editor.selected_key == key
            assert [field.label for field in _fields(app) if field.focused] == [label]
            assert app.config_editor.config.hotkey.binding == "KEY_F9"

    asyncio.run(exercise())


def test_settings_search_finds_names_across_tabs_and_escape_clears(tmp_path):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot)
            await pilot.press("slash", *"threads", "enter")
            await pilot.pause()
            assert [field.label for field in _fields(app)] == ["CPU threads"]
            assert "search: threads" in _screen_text(app)
            await pilot.press("escape")
            await pilot.pause()
            assert app.config_editor.visible_keys == TAB_KEYS["general"]

    asyncio.run(exercise())


def test_settings_footer_and_buttons_print_their_keys(tmp_path):
    async def exercise():
        app = _app(tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open(pilot)
            text = _screen_text(app)
            for label in ("[ctrl+s] Save 0 changes", "[u] Undo", "[D] Reset row", "Discard all"):
                assert label in text
            hints = text.splitlines()[-1]
            assert "space toggle" in hints and "D reset" in hints

    asyncio.run(exercise())
