# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Settings vocabulary row and its list editor."""

from __future__ import annotations

import asyncio

from textual.widgets import Input

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.vocabulary_dialog import VocabularyDialog
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config
from tests.cli.hub.test_settings_tabs import (
    IdleServices,
    _config_path,
    _field,
    _messages,
    _plain,
    _screen_text,
    _select,
)

_WITH_TERMS = default_toml().replace("vocabulary = []", 'vocabulary = ["alpha", "bravo"]', 1)


async def _open_vocabulary(pilot):
    await pilot.press("3")
    pilot.app.settings_screen.select_tab("recognition")
    await pilot.pause()
    await _select(pilot, "Vocabulary")
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(pilot.app.screen, VocabularyDialog)


def test_settings_vocabulary_row_counts_terms_and_done_makes_an_unsaved_change(tmp_path):
    assert 'vocabulary = ["alpha", "bravo"]' in _WITH_TERMS

    async def exercise():
        path = _config_path(tmp_path, _WITH_TERMS)
        app = HubApp(IdleServices(), config_path=path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_vocabulary(pilot)
            text = _screen_text(app)
            assert "▶ alpha" in text and "bravo" in text

            await pilot.press("a", *"charlie", "enter")
            await pilot.pause()
            await pilot.press("up", "up", "e", "ctrl+a", "ctrl+k", *"alpha two", "enter")
            await pilot.pause()
            assert app.screen.terms == ["alpha two", "bravo", "charlie"]
            await pilot.press("down", "delete")
            await pilot.pause()
            assert app.screen.terms == ["alpha two", "charlie"]
            assert app.config_editor.config.refine.vocabulary == ("alpha", "bravo")

            await pilot.press("enter")
            await pilot.pause()
            assert app.config_editor.config.refine.vocabulary == ("alpha two", "charlie")
            row = _field(app, "Vocabulary")
            assert row.changed
            assert _plain(row) == "[enter] Edit list… 2 terms"
            assert Config.load(path).refine.vocabulary == ("alpha", "bravo")

            await pilot.press("ctrl+s")
            await pilot.pause()
            assert Config.load(path).refine.vocabulary == ("alpha two", "charlie")
            assert not _field(app, "Vocabulary").changed

    asyncio.run(exercise())


def test_settings_vocabulary_rejects_bad_terms_with_the_config_rules(tmp_path):
    async def exercise():
        app = HubApp(IdleServices(), config_path=_config_path(tmp_path, _WITH_TERMS))
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_vocabulary(pilot)
            dialog = app.screen
            await pilot.press("a", *"  BRAVO ", "enter")
            await pilot.pause()
            assert dialog.terms == ["alpha", "bravo"]
            assert any("repeats an earlier term" in message for message in _messages(app))
            assert isinstance(app.screen.focused, Input), "the input stays open to fix the term"
            await pilot.press("ctrl+a", "ctrl+k", *("x" * 65), "enter")
            await pilot.pause()
            assert dialog.terms == ["alpha", "bravo"]
            assert any("at most 64 characters" in message for message in _messages(app))
            await pilot.press("ctrl+a", "ctrl+k", "space", "enter")
            await pilot.pause()
            assert any("must be non-empty" in message for message in _messages(app))
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("a", *"  delta ", "enter")
            await pilot.pause()
            assert dialog.terms == ["alpha", "bravo", "delta"]

            await pilot.press("escape")
            await pilot.pause()
            assert app.config_editor.config.refine.vocabulary == ("alpha", "bravo")
            assert not app.config_editor.dirty

    asyncio.run(exercise())
