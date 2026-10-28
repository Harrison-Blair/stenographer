# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit of keys, printed button keys, hint rows, help, clicks and docs (README D1-D3).

Each screen and state is driven with a pilot and fake services. The audit reads
what is on screen (hint rows, button labels, the help overlay) and compares it
with the key bindings that are active there.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

import pytest
from textual.widgets import Button, Input

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.checks_tab import ChecksTab
from stenographer.cli.hub.choice_dialog import ChoiceDialog
from stenographer.cli.hub.config_dialog import ConfigPrompt
from stenographer.cli.hub.defaults_dialog import DefaultsDialog
from stenographer.cli.hub.device_dialog import DeviceDialog
from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport, ModelEntry
from stenographer.cli.hub.export_dialog import ExportDialog
from stenographer.cli.hub.hub_screen import HubScreen
from stenographer.cli.hub.library_screen import LibraryScreen
from stenographer.cli.hub.models_dialog import ModelsDialog
from stenographer.cli.hub.quick_setup_dialog import QuickSetupDialog
from stenographer.cli.hub.record_screen import RecordScreen
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.settings_screen import SettingsScreen
from stenographer.cli.hub.transcribe_dialog import TranscribeDialog
from stenographer.cli.hub.vocabulary_dialog import VocabularyDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.focus_button import FocusButton
from stenographer.cli.hub.widgets.help_overlay import HelpOverlay
from stenographer.cli.hub.widgets.key_hints import KeyHints
from stenographer.cli.hub.widgets.sidebar import Sidebar
from tests.cli.hub.test_library import FakeServices as LibraryServices
from tests.cli.hub.test_library import _library
from tests.cli.hub.test_record_screen import _app as record_app
from tests.cli.hub.test_record_screen import _services as record_services
from tests.cli.hub.test_settings_tabs import _config_path, _select

REPO = Path(__file__).resolve().parents[3]

# A hint or a printed button key names one or more binding keys.
TOKEN_KEYS = {
    "1 2 3": ("1", "2", "3"),
    "↑↓": ("up", "down"),
    "←→": ("left", "right"),
    "PgUp/Dn": ("pageup", "pagedown"),
    "Home/End": ("home", "end"),
    "End": ("end",),
    "D": ("shift+d",),
    "Q": ("shift+q",),
    "del": ("delete",),
    "/": ("slash",),
    "?": ("question_mark",),
    "esc": ("escape",),
}
# The prompts of ``QuitConfirm`` and ``ConfigPrompt`` resolve a click by button ID.
FOCUS_BUTTON_ACTIONS = {
    "cancel-quit": "cancel",
    "confirm-quit": "confirm",
    "choice-save": "choose('save')",
    "choice-discard": "choose('discard')",
    "choice-stay": "cancel",
}
# Controls with no key of their own (README §4.6, the Export format row).
KEYLESS = re.compile(r"^(tab-\w+|config-discard|export-format-\w+)$")
PRINTED_KEY = re.compile(r"\[([^\]]+)\]")
# Keys that a focused input takes as text.
TYPED_KEYS = frozenset({"slash", "space", "question_mark"})


class SettingsServices:
    recording = False
    files_running = False
    session = None

    def update_config(self, config):
        self.config = config


def _keys(token: str) -> tuple[str, ...]:
    return TOKEN_KEYS.get(token, (token,))


def _typed(key: str) -> bool:
    return len(key) == 1 or key in TYPED_KEYS


def _report() -> DoctorReport:
    return DoctorReport(
        (
            DoctorCheck("has_mic", "microphone", "input", "ok", "alpha input", ""),
            DoctorCheck("cue_player", "sounds", "input", "warn", "bravo pack", "Pick a pack."),
            DoctorCheck("ffmpeg", "ffmpeg", "other", "fail", "not installed", "Install it."),
        ),
        (),
        checked_at=datetime(2026, 10, 27, 13, 21),
    )


def _screen_text(app: HubApp) -> str:
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


def _shown(widget) -> bool:
    return widget.display and widget.region.area > 0 and widget.visible


async def _until(pilot, condition, message: str) -> None:
    for _ in range(300):
        if condition():
            return
        await pilot.pause(0.02)
    raise AssertionError(message)


# Apps and states


def _make_app(kind: str, tmp_path: Path) -> HubApp:
    if kind == "record":
        services, _created = record_services(tmp_path)
        return record_app(services)
    if kind == "library":
        root, _sessions = _library(tmp_path)
        return HubApp(LibraryServices(root), files_home=tmp_path)
    app = HubApp(
        SettingsServices(),
        config_path=_config_path(tmp_path),
        doctor_probe=lambda _config, _path: _report(),
        model_status=lambda: (ModelEntry("alpha", "speech model", "alpha", False, "1 MB"),),
        setup_test=lambda _step, _config: "alpha test",
    )
    app.settings_screen.list_devices = lambda _key: [("0", "0: alpha input")]
    return app


async def _record(pilot, *steps: str) -> None:
    app = pilot.app
    for step in steps:
        if step == "record":
            await pilot.press("space")
            await _until(pilot, lambda: app.services.recording, "no recording")
        elif step == "pause":
            await pilot.press("space")
            await _until(pilot, lambda: app.services.session.paused, "not paused")
        elif step == "save":
            app.services.session.release.set()
            await pilot.press("enter")
            await _until(
                pilot,
                lambda: (
                    app.record_screen.record_state() == "saved"
                    and not app.services.stopping_sessions
                ),
                "not saved",
            )
        else:
            await pilot.press(step)
        await pilot.pause()
    app.refresh_view()
    await pilot.pause()


async def _library_state(pilot, *keys: str) -> None:
    app = pilot.app
    screen = app.library_screen
    await pilot.press("2")
    await _until(pilot, lambda: screen.loaded and screen.entries, "no entries")
    await _until(pilot, lambda: screen.selected_id is not None, "no selection")
    await _until(pilot, lambda: screen.detail is not None, "no detail")
    for key in keys:
        await pilot.press(key)
        await pilot.pause()
    app.refresh_view()
    await pilot.pause()


async def _settings(pilot, tab: str, *steps: str) -> None:
    app = pilot.app
    await pilot.press("3")
    await pilot.pause()
    app.settings_screen.select_tab(tab)
    await pilot.pause()
    if tab == "checks":
        await _until(pilot, lambda: app.checks_tab.report is not None, "no check report")
    for step in steps:
        if step.startswith("row:"):
            await _select(pilot, step.removeprefix("row:"))
        elif step.startswith("click:"):
            assert await pilot.click(step.removeprefix("click:"))
        elif step == "edit-config":
            app.config_editor.edit("asr.cpu_threads", "5")
        else:
            await pilot.press(step)
        await pilot.pause()
    app.refresh_view()
    await pilot.pause()


# ``(state, app kind, driver, expected screen type)``
STATES = {
    "record-idle": ("record", lambda p: _record(p), RecordScreen),
    "record-recording": ("record", lambda p: _record(p, "record"), RecordScreen),
    "record-paused": ("record", lambda p: _record(p, "record", "pause"), RecordScreen),
    "record-saved": ("record", lambda p: _record(p, "record", "save"), RecordScreen),
    "library": ("library", lambda p: _library_state(p), LibraryScreen),
    "library-search-input": ("library", lambda p: _library_state(p, "slash"), LibraryScreen),
    "settings-general": ("settings", lambda p: _settings(p, "general"), SettingsScreen),
    "settings-audio": ("settings", lambda p: _settings(p, "audio"), SettingsScreen),
    "settings-recognition": ("settings", lambda p: _settings(p, "recognition"), SettingsScreen),
    "settings-live": ("settings", lambda p: _settings(p, "live"), SettingsScreen),
    "settings-checks": ("settings", lambda p: _settings(p, "checks"), SettingsScreen),
    "settings-number-input": (
        "settings",
        lambda p: _settings(p, "recognition", "row:Idle unload", "enter"),
        SettingsScreen,
    ),
}
DIALOGS = {
    "record-device": ("record", lambda p: _record(p, "d"), DeviceDialog),
    "record-rename": ("record", lambda p: _record(p, "record", "r"), RenameDialog),
    "record-quit": ("record", lambda p: _record(p, "record", "q"), QuitConfirm),
    "saved-rename": ("record", lambda p: _record(p, "record", "save", "r"), RenameDialog),
    "library-rename": ("library", lambda p: _library_state(p, "r"), RenameDialog),
    "library-export": ("library", lambda p: _library_state(p, "x"), ExportDialog),
    "library-transcribe": ("library", lambda p: _library_state(p, "n"), TranscribeDialog),
    "library-delete": ("library", lambda p: _library_state(p, "delete"), QuitConfirm),
    "settings-choice": (
        "settings",
        lambda p: _settings(p, "general", "row:Hotkey mode", "enter"),
        ChoiceDialog,
    ),
    "settings-vocabulary": (
        "settings",
        lambda p: _settings(p, "recognition", "row:Vocabulary", "enter"),
        VocabularyDialog,
    ),
    "settings-guard": (
        "settings",
        lambda p: _settings(p, "recognition", "edit-config", "1"),
        ConfigPrompt,
    ),
    "settings-discard": (
        "settings",
        lambda p: _settings(p, "recognition", "edit-config", "click:#config-discard"),
        QuitConfirm,
    ),
    "checks-quick-setup": (
        "settings",
        lambda p: _settings(p, "checks", "shift+q"),
        QuickSetupDialog,
    ),
    "checks-models": ("settings", lambda p: _settings(p, "checks", "m"), ModelsDialog),
    "checks-defaults": ("settings", lambda p: _settings(p, "checks", "shift+d"), DefaultsDialog),
    "help": ("record", lambda p: _record(p, "question_mark"), HelpOverlay),
}


def _run_state(tmp_path, table, name, check) -> None:
    kind, drive, expected = table[name]

    async def exercise():
        app = _make_app(kind, tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            await drive(pilot)
            assert isinstance(app.screen, expected), f"{name}: {type(app.screen).__name__}"
            await check(pilot)

    asyncio.run(exercise())


# AC1: keys agree


def _key_problems(app: HubApp) -> list[str]:
    """Return each hint key, printed button key and card key with no matching binding."""
    screen = app.screen
    active = {key: item for key, item in screen.active_bindings.items() if item.enabled}
    typing = isinstance(screen.focused, Input)
    problems = []
    for hints in screen.query(KeyHints):
        if not _shown(hints):
            continue
        for token, description in hints.items:
            for key in _keys(token):
                item = active.get(key)
                if item is None:
                    problems.append(f"hint {token} {description}: no active binding {key}")
                elif typing and _typed(key) and not item.binding.priority:
                    problems.append(f"hint {token} {description}: types into the focused input")
    sidebar = next(iter(screen.query(Sidebar)), None)
    card_runs = {key: run for _label, key, run in sidebar._card_buttons} if sidebar else {}
    for button in screen.query(Button):
        if not _shown(button) or button.disabled:
            continue
        name = button.id or type(button).__name__
        if isinstance(button, HubButton):
            key, action = button.key, button.action_name
        elif isinstance(button, FocusButton):
            printed = PRINTED_KEY.search(button.plain_label.plain)
            key = printed.group(1) if printed else None
            action = FOCUS_BUTTON_ACTIONS.get(name)
        else:
            problems.append(f"button {name}: not a hub button")
            continue
        if key is None:
            if not KEYLESS.match(name):
                problems.append(f"button {name}: prints no key")
            continue
        if typing and _typed(_keys(key)[0]):
            # README §4.6: a focused input takes this key; the click still acts.
            continue
        item = active.get(_keys(key)[0])
        if item is None:
            problems.append(f"button {name} [{key}]: no active binding")
            continue
        if name.startswith("card-"):
            run = card_runs[key]
            if (run.__self__, run.__name__) != (item.node, f"action_{item.binding.action}"):
                problems.append(
                    f"card button [{key}]: runs {run.__name__}, key runs {item.binding.action}"
                )
        elif isinstance(item.node, Input) and item.node is screen.focused:
            # ``enter`` submits the focused input and the dialog handles the
            # submit; the click test presses the key and checks the action.
            continue
        elif action is not None and item.binding.action != action:
            problems.append(f"button {name} [{key}]: runs {action}, key runs {item.binding.action}")
        elif isinstance(button, HubButton) and action is not None:
            owner = next(
                node
                for node in button.ancestors_with_self
                if callable(getattr(node, f"action_{action.partition('(')[0]}", None))
            )
            if owner is not item.node:
                problems.append(f"button {name} [{key}]: runs on {owner}, key on {item.node}")
    return problems


@pytest.mark.parametrize("name", [*STATES, *DIALOGS])
def test_each_hint_and_printed_key_has_a_binding_with_the_same_action(tmp_path, name):
    async def check(pilot):
        assert _key_problems(pilot.app) == []

    _run_state(tmp_path, {**STATES, **DIALOGS}, name, check)


@pytest.mark.parametrize("name", list(STATES))
def test_help_overlay_shows_every_shown_binding_of_the_screen(tmp_path, name):
    async def check(pilot):
        app = pilot.app
        screen = app.screen
        assert isinstance(screen, HubScreen)
        active = {key: item for key, item in screen.active_bindings.items() if item.enabled}
        wanted = {item.binding.description for item in active.values() if item.binding.show}
        if isinstance(screen.focused, Input):
            # A focused input takes letters and ``?``; the overlay opens once it is closed.
            await pilot.press("escape")
            await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)
        text = _screen_text(app)
        missing = sorted(description for description in wanted if description not in text)
        assert missing == []
        assert "[esc] Close" in text
        await pilot.press("question_mark")
        await pilot.pause()
        assert app.screen is screen

    _run_state(tmp_path, STATES, name, check)


# Dialogs whose only focus is a text input; ``tab`` there cycles the format.
INPUT_ONLY_DIALOGS = frozenset({"library-export"})


@pytest.mark.parametrize("name", [name for name in DIALOGS if name != "help"])
def test_help_overlay_shows_every_shown_binding_of_the_dialog(tmp_path, name):
    async def check(pilot):
        app = pilot.app
        dialog = app.screen
        if name in INPUT_ONLY_DIALOGS:
            # README §4.6: the input is the only focus and takes ``?`` as text.
            await pilot.press("question_mark")
            await pilot.pause()
            assert app.screen is dialog
            assert dialog.focused.value.endswith("?")
            return
        if isinstance(dialog.focused, Input):
            # A focused input takes ``?`` as text; ``tab`` moves to the buttons.
            await pilot.press("tab")
            await pilot.pause()
            assert not isinstance(dialog.focused, Input), name
        active = {
            key: item
            for key, item in dialog.active_bindings.items()
            if item.enabled
        }
        wanted = {
            (HelpOverlay.help_rows({key: item})[0])
            for key, item in active.items()
            if item.binding.show
        }
        assert wanted, name
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay), name
        text = _screen_text(app)
        missing = sorted(row for row in wanted if row[0] not in text or row[1] not in text)
        assert missing == []
        assert "[esc] Close" in text
        await pilot.press("question_mark")
        await pilot.pause()
        assert app.screen is dialog

    _run_state(tmp_path, DIALOGS, name, check)


def test_help_overlay_scrolls_its_rows_and_keeps_its_close_button_on_a_short_terminal():
    async def exercise():
        app = HubApp(SettingsServices())
        async with app.run_test(size=(150, 20)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            overlay = app.screen
            assert isinstance(overlay, HelpOverlay)
            assert "[esc] Close" in _screen_text(app)
            assert "Previous entry" in _screen_text(app)
            body = overlay.body_widget()
            body.scroll_end(animate=False)
            await pilot.pause()
            assert overlay.rows[-1][1] in _screen_text(app)

    asyncio.run(exercise())


# AC2: clicks


@pytest.mark.parametrize("name", [*STATES, *DIALOGS])
def test_each_button_click_runs_the_action_of_its_key(tmp_path, name):
    """A click and the printed key reach the same action method with the same arguments."""

    async def check(pilot):
        app = pilot.app
        screen = app.screen
        buttons = [
            button
            for button in screen.query(HubButton)
            if _shown(button) and not button.disabled and button.key and button.action_name
        ]
        for button in buttons:
            if screen.query(f"#{button.id}").first() is not button:
                continue
            action = button.action_name
            method = f"action_{action.partition('(')[0]}"
            owner = next(
                n for n in button.ancestors_with_self if callable(getattr(n, method, None))
            )
            calls = []
            setattr(owner, method, lambda *args, _calls=calls: _calls.append(args))
            try:
                assert await pilot.click(f"#{button.id}"), button.id
                await pilot.pause()
                key = _keys(button.key)[0]
                item = screen.active_bindings.get(key)
                shadowed = item is not None and item.node is screen.focused
                if not isinstance(screen.focused, Input) or not (_typed(key) or shadowed):
                    await pilot.press(key)
                    await pilot.pause()
                    assert len(calls) == 2, f"{button.id}: {calls}"
                    assert calls[0] == calls[1], f"{button.id}: {calls}"
                else:
                    assert len(calls) == 1, f"{button.id}: {calls}"
            finally:
                delattr(owner, method)
            assert app.screen is screen, f"{button.id} left the screen"

    _run_state(tmp_path, {**STATES, **DIALOGS}, name, check)


def test_nav_rows_and_settings_tabs_answer_a_click(tmp_path):
    async def exercise():
        app = _make_app("settings", tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            for row, screen in ((1, "library"), (2, "settings"), (0, "record")):
                assert await pilot.click("#sidebar", offset=(4, row))
                await pilot.pause()
                assert app.current_mode == screen
            await pilot.press("3")
            await pilot.pause()
            for tab in ("audio", "recognition", "live", "checks", "general"):
                assert await pilot.click(f"#tab-{tab}")
                await pilot.pause()
                assert app.settings_screen.tab == tab
                assert app.screen.query_one(f"#tab-{tab}", HubButton).label.plain.startswith("▶")

    asyncio.run(exercise())


def test_context_card_buttons_run_the_action_of_their_key(tmp_path):
    async def exercise():
        app = _make_app("record", tmp_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await _record(pilot, "record")
            assert await pilot.click("#card-r")
            await pilot.pause()
            assert isinstance(app.screen, RenameDialog)

        probes = []
        app = _make_app("settings", tmp_path / "settings")
        app.checks_tab._doctor_probe = lambda _config, _path: probes.append(1) or _report()
        async with app.run_test(size=(150, 45)) as pilot:
            await _settings(pilot, "checks")
            await _until(pilot, lambda: not app.checks_tab.checking, "checks still run")
            before = len(probes)
            assert await pilot.click("#card-r")
            await _until(pilot, lambda: len(probes) == before + 1, "the card did not run checks")
            await _until(pilot, lambda: not app.checks_tab.checking, "checks still run")
            await pilot.press("r")
            await _until(pilot, lambda: len(probes) == before + 2, "r did not run checks")

    (tmp_path / "settings").mkdir()
    asyncio.run(exercise())


# AC3: docs

DOC_KEY_NAMES = {"/": "slash", "?": "question_mark"}
DOC_SECTIONS = {
    "Screens and keys": HubApp,
    "Record": RecordScreen,
    "Library": LibraryScreen,
    "Settings": SettingsScreen,
    "Checks": ChecksTab,
}


def _doc_key_tables() -> dict[str, set[str]]:
    """Return the keys of each ``| Key |`` table in docs/hub.md by its heading."""
    tables: dict[str, set[str]] = {}
    heading = ""
    in_table = False
    for line in (REPO / "docs" / "hub.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if line.startswith("| Key |"):
            in_table = True
            tables.setdefault(heading, set())
            continue
        if in_table and line.startswith("|"):
            cell = line.split("|")[1]
            for key in re.findall(r"`([^`]+)`", cell):
                tables[heading].add(DOC_KEY_NAMES.get(key, key))
            continue
        in_table = False
    return tables


def _class_keys(owner) -> set[str]:
    keys = set()
    for binding in owner.BINDINGS:
        key, show = (
            (binding[0], True) if isinstance(binding, tuple) else (binding.key, binding.show)
        )
        if show:
            keys.add(key)
    return keys - {"---"}


@pytest.mark.parametrize("section", list(DOC_SECTIONS))
def test_docs_key_tables_match_the_bindings(section):
    tables = _doc_key_tables()
    assert tables.get(section, set()) == _class_keys(DOC_SECTIONS[section])


def test_readme_and_site_describe_three_screens_and_no_live_command():
    for path in (REPO / "README.md", REPO / "site" / "index.html"):
        text = path.read_text(encoding="utf-8")
        assert "stenographer live" not in text, path
        assert re.search(r"three[- ]screen", text), path
        for screen in ("Record", "Library", "Settings"):
            assert screen in text, (path, screen)
        assert not re.search(r"\bLive, and Files\b|\bLive and Files\b", text), path


def test_hub_uses_one_fail_glyph():
    hub = REPO / "src" / "stenographer" / "cli" / "hub"
    docs = [REPO / "docs" / "hub.md", REPO / "README.md", REPO / "site" / "index.html"]
    offenders = [
        str(path.relative_to(REPO))
        for path in [*sorted(hub.rglob("*.py")), *docs]
        if "\N{BALLOT X}" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_docs_name_no_files_section():
    text = (REPO / "docs" / "hub.md").read_text(encoding="utf-8")
    assert "Record, and Files" not in text
    assert "Files job" not in text


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()
