# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration editing behavior in the hub."""

from __future__ import annotations

import asyncio

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
            assert "hotkey" in content
            assert "audio" in content
            assert "asr" in content
            assert "analytics" in content
            assert "delivery" in content
            assert "binding" in content
            assert "KEY_RIGHTCTRL" in content
            assert "Default:" in content
            assert "Agent binding" in content
            assert "Changes apply to new sessions and jobs" in content

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
