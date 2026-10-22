# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration editing behavior in the hub."""

from __future__ import annotations

import asyncio

from rich.cells import cell_len
from rich.color import Color
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
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
    await pilot.press("4", "/")
    await pilot.press(*tuple("asr.cpu_threads"), "enter", "enter")
    await pilot.press("ctrl+a", "ctrl+k", *tuple(value), "enter")


def _notification_messages(app):
    return [notification.message for notification in app._notifications]


def test_config_section_shows_model_groups_values_defaults_and_help(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test() as pilot:
            await pilot.press("4")
            content = str(app.query_one("#section-content", Static).render())
            details = app.query_one("#config-selected-help", Static).render().plain
            groups = app.query_one("#config-group-list", Static).render().plain
            group_names = [line.strip().removeprefix("▶ ").strip() for line in groups.splitlines()]
            assert group_names == [
                "hotkey",
                "audio",
                "asr",
                "live",
                "refine",
                "feedback",
                "analytics",
                "delivery",
            ]
            assert "binding" in content
            assert "KEY_RIGHTCTRL" in content
            assert "Changes apply to new sessions and jobs" not in content
            assert "Default:" in details
            assert "Agent binding" in details

    asyncio.run(exercise())


def test_config_board_layout_has_group_selector_settings_and_help_panels(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            await pilot.pause()
            groups = app.query_one("#config-group-list", Static)
            settings = app.query_one("#main-content", Vertical)
            note = app.query_one("#config-selected-help", Static)
            section = app.query_one("#section-content", Static)
            assert isinstance(groups.parent, Horizontal)
            assert groups.parent is settings.parent
            assert note.parent is settings
            assert [child.id for child in settings.children] == [
                "section-content",
                "config-selected-help",
            ]
            assert groups.region.x < settings.region.x
            assert groups.region.y == settings.region.y
            assert groups.border_title == "group"
            assert settings.border_title == "asr"
            assert section.region.y < note.region.y
            assert groups.styles.border_left[0]
            assert settings.styles.border_left[0]

            group_text = groups.render()
            assert "▶ asr" in group_text.plain
            offset = group_text.plain.index("▶")
            selected = next(
                span.style.rich_style
                for span in group_text.spans
                if span.start <= offset < span.end
            )
            assert selected.bold
            assert selected.color == Color.parse("#5fd7ff")
            assert selected.bgcolor is None or selected.bgcolor.is_default
            normal_offset = group_text.plain.index("hotkey")
            normal = group_text.get_style_at_offset(normal_offset).rich_style
            assert not normal.bold
            assert normal.color is None or normal.color.is_default
            assert normal.bgcolor is None or normal.bgcolor.is_default
            group_names = [
                line.strip().removeprefix("▶ ").strip() for line in group_text.plain.splitlines()
            ]
            assert group_names == [
                "hotkey",
                "audio",
                "asr",
                "live",
                "refine",
                "feedback",
                "analytics",
                "delivery",
            ]

            settings_text = section.render().plain
            assert "idle_unload_seconds" in settings_text
            assert "Unload the idle recognition worker" in note.render().plain

            await pilot.press("down")
            assert app.config_editor.selected_key == "asr.cpu_threads"
            assert "Recognition worker CPU threads" in note.render().plain
            await pilot.press("up")
            assert app.config_editor.selected_key == "asr.idle_unload_seconds"
            await pilot.press("down")
            assert app.config_editor.selected_key == "asr.cpu_threads"

    asyncio.run(exercise())


def test_config_settings_title_uses_legible_default_bold_style(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            settings = app.query_one("#main-content")
            assert (
                settings.styles.border_title_color.ansi,
                settings.styles.border_title_style.bold,
            ) == (-1, True)

    asyncio.run(exercise())


def test_config_settings_use_one_compact_name_value_row_per_key(tmp_path):
    content = default_toml().replace("cpu_threads = 0", "cpu_threads = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            settings = app.query_one("#section-content", Static).render().plain
            rows = [line.strip().removeprefix("▶ ") for line in settings.splitlines()]
            assert [line.split()[0] for line in rows] == ["idle_unload_seconds", "cpu_threads"]
            assert "▶ idle_unload_seconds" in settings
            assert "▶ asr.idle_unload_seconds" not in settings
            assert "Default:" not in settings
            assert "Unload the idle recognition worker" not in settings
            assert "5 ●" in settings

    asyncio.run(exercise())


def test_config_selected_key_is_bold_accent_and_default_difference_has_warn_dot(tmp_path):
    content = default_toml().replace("cpu_threads = 0", "cpu_threads = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right", "down")
            settings = app.query_one("#section-content", Static).render()
            row = next(line for line in settings.plain.splitlines() if "cpu_threads" in line)
            assert "▶ cpu_threads" in row and "5 ●" in row
            marker = settings.plain.index("▶ cpu_threads")
            selected_row_start = settings.plain.rfind("\n", 0, marker) + 1
            selected_value = settings.plain.index("5", marker + len("▶ cpu_threads"))
            value_row = next(
                line for line in settings.plain.splitlines() if "idle_unload_seconds" in line
            )
            assert cell_len("▶ ") == cell_len("  ")
            assert selected_value - selected_row_start == value_row.index("900")
            for offset in range(marker + len("▶ cpu_threads"), selected_value):
                gap_style = settings.get_style_at_offset(offset).rich_style
                assert gap_style.bold
                assert gap_style.color == Color.parse("#5fd7ff")
            selected = settings.get_style_at_offset(marker).rich_style
            assert selected.bold
            assert selected.color == Color.parse("#5fd7ff")
            assert selected.bgcolor is None or selected.bgcolor.is_default
            warning = settings.plain.index("●")
            assert settings.get_style_at_offset(warning).rich_style.color == Color.parse("#ffaf5f")

    asyncio.run(exercise())


def test_config_shows_only_selected_key_help(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            content = app.query_one("#section-content", Static).render().plain
            details = app.query_one("#config-selected-help", Static).render().plain
            assert "Default:" not in content
            assert "Unload the idle recognition worker" not in content
            assert "Default: 900" in details
            assert "Unload the idle recognition worker" in details
            assert "\n" not in details

            await pilot.press("down")
            content = app.query_one("#section-content", Static).render().plain
            details = app.query_one("#config-selected-help", Static).render().plain
            assert "Default:" not in content
            assert "Default: 0" in details
            assert "Recognition worker CPU threads" in details
            assert "docs/transcription-experiments.md" not in details
            assert "Unload the idle recognition worker" not in details
            assert "\n" not in details

    asyncio.run(exercise())


def test_config_sidebar_card_shows_path_and_unsaved_change_count(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("4")
            card = app.query_one("#sidebar-card", Static)
            assert "config.toml" in card.render().plain
            assert "0 unsaved changes" in card.render().plain

            app.config_editor.edit("asr.cpu_threads", "3")
            app.config_editor.edit("asr.idle_unload_seconds", "60")
            app._refresh_view()
            assert "2 unsaved changes" in card.render().plain
            rendered = card.render()
            count_offset = rendered.plain.index("2 unsaved changes")
            count_style = rendered.get_style_at_offset(count_offset).rich_style
            assert count_style.color == Color.parse("#ffaf5f")

            app.config_editor.undo()
            app._refresh_view()
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
            await pilot.press("4", "/")
            await pilot.press(*tuple("live.diarize_mic"), "enter")
            assert app.config_editor.selected_key == "live.diarize_mic"
            details = app.query_one("#config-selected-help", Static).render().plain
            assert "microphone" in details
            await pilot.press("enter")
            await pilot.press("ctrl+a", "ctrl+k", *tuple("true"), "enter")
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
            await pilot.press("4", "enter", "ctrl+s")
            content = str(app.query_one("#section-content", Static).render())
            assert app.config_editor.read_only
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
            await pilot.press("4", "/")
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
            assert app.current_section == "files"
            assert not app.config_editor.dirty
            assert Config.load(path).asr.cpu_threads == Config.defaults().asr.cpu_threads

    asyncio.run(exercise())
