# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration editing behavior in the hub."""

from __future__ import annotations

import asyncio

from rich.cells import cell_len
from rich.color import Color
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.widgets.field import Field
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config


class FakeServices:
    recording = False
    files_running = False

    def update_config(self, config):
        self.config = config


def _config_path(tmp_path, content=None):
    path = tmp_path / "config.toml"
    path.write_text(default_toml() if content is None else content, encoding="utf-8")
    return path


async def _edit_cpu_threads(pilot, value):
    await pilot.press("3", "/")
    await pilot.press(*tuple("asr.cpu_threads"), "enter", "enter")
    await pilot.press("ctrl+a", "ctrl+k", *tuple(value), "enter")


def _fields(app) -> list[Field]:
    return list(app.settings_screen.query("#config-rows Field").results(Field))


def _field(app, label):
    return next(field for field in _fields(app) if field.label == label)


def _focused(app) -> Field:
    return next(field for field in _fields(app) if field.focused)


def _notification_messages(app):
    return [notification.message for notification in app._notifications]


def test_settings_general_tab_shows_values_defaults_and_help(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.pause()
            labels = [field.label for field in _fields(app)]
            focused = _focused(app)
            assert app.settings_screen.tab == "general"
            assert focused.label == "Agent key"
            assert focused.control.plain == "KEY_RIGHTCTRL"
            assert "CPU threads" not in labels
            assert "Agent binding" in focused.help_text
            assert "default KEY_RIGHTCTRL" in focused.help_text

    asyncio.run(exercise())


def test_settings_tab_keys_follow_the_tab_mapping_and_rows_move(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "right", "right")
            await pilot.pause()
            assert app.settings_screen.tab == "recognition"
            assert app.screen.query_one("#tab-recognition").has_class("-selected")
            assert not app.screen.query_one("#tab-general").has_class("-selected")
            assert app.config_editor.visible_keys == (
                "asr.idle_unload_seconds",
                "asr.cpu_threads",
                "refine.vocabulary",
                "refine.enabled",
                "refine.host",
                "refine.model",
                "refine.min_words",
                "refine.structured_output",
            )
            assert _focused(app).label == "Idle unload"
            assert "idle worker unloads" in _focused(app).help_text

            await pilot.press("down")
            assert app.config_editor.selected_key == "asr.cpu_threads"
            assert _focused(app).label == "CPU threads"
            assert "0 = automatic" in _focused(app).help_text
            await pilot.press("up")
            assert app.config_editor.selected_key == "asr.idle_unload_seconds"

            await pilot.press("right")
            assert app.config_editor.visible_keys == ("live.diarize_mic",)

    asyncio.run(exercise())


def test_config_settings_use_one_compact_label_value_help_row_per_key(tmp_path):
    content = default_toml().replace("cpu_threads = 0", "cpu_threads = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "right", "right")
            await pilot.pause()
            rows = [strip.text for strip in app.screen._compositor.render_strips()]
            idle = next(row for row in rows if "Idle unload" in row)
            threads = next(row for row in rows if "CPU threads" in row)
            assert "▶  Idle unload" in idle and "900 s" in idle and "idle worker unloads" in idle
            assert "▶" not in threads and " 5 " in threads and "0 = automatic" in threads
            assert "Default:" not in "\n".join(rows)
            assert idle.index("Idle unload") == threads.index("CPU threads")

    asyncio.run(exercise())


def test_config_focused_row_is_bold_accent_and_unsaved_change_has_warn_dot(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "right", "right", "down", "enter", "ctrl+a", "ctrl+k", "5")
            await pilot.press("enter")
            await pilot.pause()
            row = _field(app, "CPU threads")
            assert row.focused and row.changed
            rendered = app.screen._compositor.render_strips()
            line = next(strip for strip in rendered if "CPU threads" in strip.text)
            assert "▶● CPU threads" in line.text
            styles = {segment.text: segment.style for segment in line if segment.text.strip()}
            label = next(style for text, style in styles.items() if "CPU threads" in text)
            assert label.bold and label.color == Color.parse("#5fd7ff")
            assert label.bgcolor is None or label.bgcolor.is_default
            dot = next(style for text, style in styles.items() if "●" in text)
            assert dot.color == Color.parse("#ffaf5f")
            assert cell_len("▶●") == 2

    asyncio.run(exercise())


def test_config_shows_the_default_only_in_the_focused_row_help(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "right", "right")
            await pilot.pause()
            assert "default 900" in _field(app, "Idle unload").help_text
            assert "default" not in _field(app, "CPU threads").help_text
            await pilot.press("down")
            assert "default" not in _field(app, "Idle unload").help_text
            assert _field(app, "CPU threads").help_text == "0 = automatic · default 0"

    asyncio.run(exercise())


def test_config_sidebar_card_shows_path_and_unsaved_change_count(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("3")
            card = app.screen.query_one("#sidebar-card", Static)
            assert "config.toml" in card.render().plain
            assert "0 unsaved changes" in card.render().plain

            app.config_editor.edit("asr.cpu_threads", "3")
            app.config_editor.edit("asr.idle_unload_seconds", "60")
            app.refresh_view()
            assert "2 unsaved changes" in card.render().plain
            rendered = card.render()
            count_offset = rendered.plain.index("2 unsaved changes")
            count_style = rendered.get_style_at_offset(count_offset).rich_style
            assert count_style.color == Color.parse("#ffaf5f")

            app.config_editor.undo()
            app.refresh_view()
            assert "1 unsaved change" in card.render().plain

    asyncio.run(exercise())


def test_edit_undo_and_reset_use_validated_config_values(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await _edit_cpu_threads(pilot, "3")
            assert app.config_editor.config.asr.cpu_threads == 3
            await _edit_cpu_threads(pilot, "5")
            assert app.config_editor.config.asr.cpu_threads == 5

            await pilot.press("u")
            assert app.config_editor.config.asr.cpu_threads == 3
            await pilot.press("shift+d")
            assert app.config_editor.config.asr.cpu_threads == Config.defaults().asr.cpu_threads
            assert not app.config_editor.dirty
            assert Config.load(path).asr.cpu_threads == Config.defaults().asr.cpu_threads

    asyncio.run(exercise())


def test_config_live_group_edits_and_saves_mic_diarization(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("3", "/")
            await pilot.press(*tuple("live.diarize_mic"), "enter")
            await pilot.pause()
            assert app.config_editor.selected_key == "live.diarize_mic"
            assert "microphone" in _focused(app).help_text
            await pilot.press("enter")
            assert app.config_editor.config.live.diarize_mic is True
            await pilot.press("ctrl+s")
            assert Config.load(path).live.diarize_mic is True

    asyncio.run(exercise())


def test_invalid_edit_is_rejected_by_config_validation(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test() as pilot:
            await _edit_cpu_threads(pilot, "100")
            assert app.config_editor.config.asr.cpu_threads == Config.defaults().asr.cpu_threads
            assert not app.config_editor.dirty
            assert any("asr.cpu_threads" in message for message in _notification_messages(app))

    asyncio.run(exercise())


def test_save_writes_validated_config_and_timestamped_backup(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        original = path.read_bytes()
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await _edit_cpu_threads(pilot, "5")
            await pilot.press("ctrl+s")
            assert Config.load(path).asr.cpu_threads == 5
            backups = list(tmp_path.glob("config.toml.bak-*"))
            assert len(backups) == 1
            assert backups[0].read_bytes() == original
            assert app.services.config == Config.load(path)
            assert not app.config_editor.dirty

    asyncio.run(exercise())


def test_conflict_keeps_external_config_and_unsaved_draft(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await _edit_cpu_threads(pilot, "5")
            external = path.read_bytes() + b"\n# external edit\n"
            path.write_bytes(external)
            await pilot.press("ctrl+s")
            assert path.read_bytes() == external
            assert app.config_editor.config.asr.cpu_threads == 5
            assert app.config_editor.dirty
            assert any(
                "changed while setup was running" in message
                for message in _notification_messages(app)
            )

    asyncio.run(exercise())


def test_invalid_config_is_read_only_and_shows_error_and_fix_path(tmp_path):
    async def exercise():
        path = _config_path(tmp_path, "[stenographer.asr]\ncpu_threads = 100\n")
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("3", "enter", "ctrl+s")
            await pilot.pause()
            content = str(app.screen.query_one("#config-message", Static).render())
            assert app.config_editor.read_only
            assert not app.screen.query_one("#config-actions").display
            assert "read-only" in content
            assert str(path) in content
            assert "asr.cpu_threads" in content
            assert path.read_text(encoding="utf-8") == "[stenographer.asr]\ncpu_threads = 100\n"

    asyncio.run(exercise())


def test_search_selects_a_key_and_unsaved_navigation_asks_for_discard(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("3", "/")
            await pilot.press(*tuple("asr.cpu_threads"), "enter")
            assert app.config_editor.selected_key == "asr.cpu_threads"
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
            assert Config.load(path).asr.cpu_threads == Config.defaults().asr.cpu_threads

    asyncio.run(exercise())
