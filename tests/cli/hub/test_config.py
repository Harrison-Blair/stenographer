# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration editing behavior in the hub."""

from __future__ import annotations

import asyncio

from rich.cells import cell_len
from rich.color import Color
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

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


async def _edit_beam(pilot, value):
    await pilot.press("4", "/")
    await pilot.press(*tuple("asr.beam_size"), "enter", "enter")
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


def test_config_board_layout_has_group_selector_settings_and_hotwords_panels(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            await pilot.pause()
            groups = app.query_one("#config-group-list", Static)
            settings = app.query_one("#main-content", Vertical)
            hotwords = app.query_one("#config-hotwords", Static)
            note = app.query_one("#config-selected-help", Static)
            section = app.query_one("#section-content", Static)
            assert isinstance(groups.parent, Horizontal)
            assert groups.parent is settings.parent
            assert hotwords.parent is settings and note.parent is settings
            assert groups.region.x < settings.region.x
            assert groups.region.y == settings.region.y
            assert groups.border_title == "group"
            assert settings.border_title == "asr"
            assert section.region.y < hotwords.region.y < note.region.y
            assert groups.styles.border_left[0]
            assert settings.styles.border_left[0]
            assert hotwords.styles.border_top[0]

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
            assert "model" in settings_text
            assert "asr.hotwords" not in settings_text
            assert "context from recent lines" not in settings_text
            assert "hotwords" in hotwords.render().plain
            assert "none" in hotwords.render().plain
            assert "0 words" not in hotwords.render().plain
            assert "Cached speech-recognition model" in note.render().plain

            await pilot.press("down", "down")
            assert "docs/transcription-experiments.md" in note.render().plain
            assert "CPU model and context screen" in note.render().plain
            await pilot.press("up", "up", "down", "down", "down")
            assert app.config_editor.selected_key == "asr.hotwords"
            assert "▶" in hotwords.render().plain
            await pilot.press("enter")
            app.screen.query_one("#config-prompt-input", Input).value = "Alpha, Beta"
            await pilot.press("enter")
            assert app.config_editor.value("asr.hotwords") == "Alpha, Beta"
            assert "Alpha, Beta" in hotwords.render().plain
            assert "…" not in hotwords.render().plain

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


def test_config_hotwords_value_shows_preview_and_word_count(tmp_path):
    content = default_toml().replace(
        'hotwords = ""',
        'hotwords = "Alpha, Beta, Gamma, Delta, Epsilon, Zeta, Eta, Theta, Iota"',
    )

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            hotwords = app.query_one("#config-hotwords", Static)
            rendered = hotwords.render()
            assert "Alpha, Beta, Gamma, Delta, Epsilon, Zeta, Eta, Theta, Iota" in rendered.plain
            assert "…" not in rendered.plain
            assert rendered.plain.endswith("●")
            warning = rendered.plain.index("●")
            assert rendered.get_style_at_offset(warning).rich_style.color == Color.parse("#ffaf5f")
            assert hotwords.styles.background.a == 0

    asyncio.run(exercise())


def test_config_hotwords_truncate_to_fit_the_value_line(tmp_path):
    terms = [f"A{index:02}" for index in range(1, 41)]
    content = default_toml().replace('hotwords = ""', f'hotwords = "{", ".join(terms)}"')

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            hotwords = app.query_one("#config-hotwords", Static)
            line = hotwords.render().plain.splitlines()[1]
            assert "A16" in line
            assert "A17" not in line
            assert line.endswith("… 40 words ●")
            assert cell_len(line) <= hotwords.content_size.width

    asyncio.run(exercise())


def test_config_hotwords_truncate_wide_terms_to_fit_the_value_line(tmp_path):
    term = "界" * 100
    content = default_toml().replace('hotwords = ""', f'hotwords = "{term}"')

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            hotwords = app.query_one("#config-hotwords", Static)
            line = hotwords.render().plain.splitlines()[1]
            assert line.endswith("… 1 words ●")
            assert cell_len(line) <= hotwords.content_size.width

    asyncio.run(exercise())


def test_config_settings_use_one_compact_name_value_row_per_key(tmp_path):
    content = default_toml().replace("beam_size = 1", "beam_size = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            settings = app.query_one("#section-content", Static).render().plain
            rows = [line.strip().removeprefix("▶ ") for line in settings.splitlines()]
            assert [line.split()[0] for line in rows] == [
                "model",
                "compute_type",
                "beam_size",
                "initial_prompt",
                "vad_filter",
                "silence_threshold",
                "idle_unload_seconds",
                "cpu_threads",
            ]
            assert "▶ model" in settings
            assert "▶ asr.model" not in settings
            assert "Default:" not in settings
            assert "Cached speech-recognition model" not in settings
            assert "asr.hotwords" not in settings
            assert "context from recent lines" not in settings
            assert "5 ●" in settings

    asyncio.run(exercise())


def test_config_selected_key_is_bold_accent_and_default_difference_has_warn_dot(tmp_path):
    content = default_toml().replace("beam_size = 1", "beam_size = 5")

    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path, content))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right", "down", "down")
            settings = app.query_one("#section-content", Static).render()
            row = next(line for line in settings.plain.splitlines() if "beam_size" in line)
            assert "▶ beam_size" in row and "5 ●" in row
            marker = settings.plain.index("▶ beam_size")
            selected_row_start = settings.plain.rfind("\n", 0, marker) + 1
            selected_value = settings.plain.index("5", marker + len("▶ beam_size"))
            value_row = next(line for line in settings.plain.splitlines() if "compute_type" in line)
            assert cell_len("▶ ") == cell_len("  ")
            assert selected_value - selected_row_start == value_row.index("int8")
            for offset in range(marker + len("▶ beam_size"), selected_value):
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


def test_config_shows_only_selected_key_help_and_beam_benchmark(tmp_path):
    async def exercise():
        app = HubApp(FakeServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("4", "right", "right")
            content = app.query_one("#section-content", Static).render().plain
            details = app.query_one("#config-selected-help", Static).render().plain
            assert "Default:" not in content
            assert "Cached speech-recognition model" not in content
            assert "Default:" in details
            assert "Cached speech-recognition model" in details
            assert "Search width" not in details
            assert "\n" not in details

            await pilot.press("down", "down")
            content = app.query_one("#section-content", Static).render().plain
            details = app.query_one("#config-selected-help", Static).render().plain
            assert "Default:" not in content
            assert "Default: 1" in details
            assert "Wider search can improve word accuracy" in details
            assert "docs/transcription-experiments.md" in details
            assert "CPU model and context screen" in details
            assert "Cached speech-recognition model" not in details
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

            app.config_editor.edit("asr.beam_size", "3")
            app.config_editor.edit("asr.cpu_threads", "2")
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
            await _edit_beam(pilot, "3")
            assert app.config_editor.config.asr.beam_size == 3
            await _edit_beam(pilot, "5")
            assert app.config_editor.config.asr.beam_size == 5

            await pilot.press("u")
            assert app.config_editor.config.asr.beam_size == 3
            await pilot.press("shift+d")
            assert app.config_editor.config.asr.beam_size == Config.defaults().asr.beam_size
            assert not app.config_editor.dirty
            assert Config.load(path).asr.beam_size == Config.defaults().asr.beam_size

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
            await _edit_beam(pilot, "11")
            assert app.config_editor.config.asr.beam_size == Config.defaults().asr.beam_size
            assert not app.config_editor.dirty
            assert any("asr.beam_size" in message for message in _notification_messages(app))

    asyncio.run(exercise())


def test_save_writes_validated_config_and_timestamped_backup(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        original = path.read_bytes()
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await _edit_beam(pilot, "5")
            await pilot.press("ctrl+s")
            assert Config.load(path).asr.beam_size == 5
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
            await _edit_beam(pilot, "5")
            external = path.read_bytes() + b"\n# external edit\n"
            path.write_bytes(external)
            await pilot.press("ctrl+s")
            assert path.read_bytes() == external
            assert app.config_editor.config.asr.beam_size == 5
            assert app.config_editor.dirty
            assert any(
                "changed while setup was running" in message
                for message in _notification_messages(app)
            )

    asyncio.run(exercise())


def test_invalid_config_is_read_only_and_shows_error_and_fix_path(tmp_path):
    async def exercise():
        path = _config_path(tmp_path, "[stenographer.asr]\nbeam_size = 0\n")
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("4", "enter", "ctrl+s")
            content = str(app.query_one("#section-content", Static).render())
            assert app.config_editor.read_only
            assert "read-only" in content
            assert str(path) in content
            assert "asr.beam_size" in content
            assert path.read_text(encoding="utf-8") == "[stenographer.asr]\nbeam_size = 0\n"

    asyncio.run(exercise())


def test_search_selects_a_key_and_unsaved_navigation_asks_for_discard(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(FakeServices(), config_path=path)
        async with app.run_test() as pilot:
            await pilot.press("4", "/")
            await pilot.press(*tuple("asr.beam_size"), "enter")
            assert app.config_editor.selected_key == "asr.beam_size"
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
            assert Config.load(path).asr.beam_size == Config.defaults().asr.beam_size

    asyncio.run(exercise())
