# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Checks tab of Settings (README §4.7, D12, D16)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest
from rich.color import Color
from textual.widgets import Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.defaults_dialog import DefaultsDialog
from stenographer.cli.hub.doctor_view import (
    DoctorCheck,
    DoctorReport,
    ModelEntry,
    recent_warnings,
    safe_warning_lines,
)
from stenographer.cli.hub.models_dialog import ModelsDialog
from stenographer.cli.hub.quick_setup_dialog import QuickSetupDialog
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.cli.hub.widgets.selectable_list import SelectableList
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.document import ConfigDocument
from stenographer.lib.config.models import Config
from stenographer.lib.logging.pipeline import fmt_event, log_failure

MARKER = "zuluprivatemarker"
FAIL = "\N{MULTIPLICATION SIGN}"


class FakeServices:
    recording = False
    files_running = False
    session = None


def _check(check_id, label, group, status="ok", detail="available", fix="", **extra):
    return DoctorCheck(check_id, label, group, status, detail, fix, **extra)


def _board_report(warnings=()) -> DoctorReport:
    """A synthetic report in a mixed order; the tab shows it by group."""
    return DoctorReport(
        (
            _check("ffmpeg", "ffmpeg", "other", "fail", "ffmpeg is not installed", "Install it."),
            _check("model_cached", "speech model", "engine", detail="alpha model · pinned"),
            _check("key_injector_ok", "input access", "input", detail="uinput group ok"),
            _check("has_mic", "microphone", "input", detail="Default input"),
            _check("hotkey_access_ok", "hotkey", "input", detail="RCtrl · hybrid"),
            _check(
                "cue_player",
                "sounds",
                "input",
                "warn",
                "pack bravo · 1 cue missing",
                "Choose another sound pack.",
                explanation="The sound pack bravo has no charlie cue.",
                path="/tmp/sounds/bravo",
            ),
            _check("live_models_cached", "voice models", "engine", detail="alpha · bravo"),
            _check("system_service", "system service", "engine", detail="enabled · running"),
        ),
        tuple(warnings),
        checked_at=datetime(2026, 10, 27, 13, 21),
    )


def _app(report=None, **kwargs) -> HubApp:
    if report is None:
        report = _board_report()
    kwargs.setdefault("doctor_probe", lambda _config, _path: report)
    return HubApp(FakeServices(), **kwargs)


async def _open_checks(pilot) -> None:
    await pilot.press("3", "left")
    await _settle(pilot, lambda: pilot.app.checks_tab.report is not None)


async def _settle(pilot, condition) -> None:
    for _ in range(200):
        if condition():
            break
        await pilot.pause(0.01)
    assert condition()


def _plain(app, selector: str) -> str:
    return app.screen.query_one(selector, Static).render().plain


def _button(app, selector: str) -> HubButton:
    return app.screen.query_one(selector, HubButton)


# V1: list, detail, card, badge


def test_checks_list_groups_rows_with_glyphs_in_the_board_order():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert _plain(app, "#checks-section-input") == "input"
            assert _plain(app, "#checks-section-engine") == "engine"
            assert _plain(app, "#checks-section-other") == "other"
            inputs = _plain(app, "#checks-input").splitlines()
            assert [row[2:].split()[1] for row in inputs] == [
                "input",
                "microphone",
                "hotkey",
                "sounds",
            ]
            assert inputs[0].startswith("  ✓ input access")
            assert "uinput group ok" in inputs[0]
            assert inputs[3].startswith("▶ ! sounds")
            engine = _plain(app, "#checks-engine").splitlines()
            assert [row[4:18].strip() for row in engine] == [
                "speech model",
                "voice models",
                "system service",
            ]
            other = _plain(app, "#checks-other").splitlines()
            assert other == [other[0]]
            assert other[0].startswith(f"  {FAIL} ffmpeg")

    asyncio.run(exercise())


def test_checks_rows_cut_a_long_detail_and_never_wrap():
    long_detail = "alpha bravo charlie delta echo foxtrot golf hotel india juliett " * 3
    report = DoctorReport((_check("has_mic", "microphone", "input", detail=long_detail),), ())

    async def exercise():
        app = _app(report)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            rows = _plain(app, "#checks-input").splitlines()
            assert len(rows) == 1
            assert rows[0].endswith("…")
            width = app.screen.query_one("#checks-input", SelectableList).size.width
            assert len(rows[0]) <= width

    asyncio.run(exercise())


def test_checks_glyphs_carry_the_state_and_colour_only_adds():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("down")
            for selector, glyph, tone in (
                ("#checks-input", "✓", "#6ee69a"),
                ("#checks-other", FAIL, "#ff875f"),
            ):
                text = app.screen.query_one(selector, Static).render()
                style = text.get_style_at_offset(text.plain.index(glyph))
                assert style.rich_style.color.get_truecolor() == Color.parse(tone).get_truecolor()
                label = text.get_style_at_offset(text.plain.index(glyph) + 2)
                assert label.rich_style.color is None, "only the glyph takes the state colour"
            head = app.screen.query_one("#checks-detail-head", Static).render()
            assert head.get_style_at_offset(0).rich_style.color is not None
            assert head.get_style_at_offset(2).rich_style.color is None

    asyncio.run(exercise())


def test_checks_detail_shows_title_state_explanation_path_and_buttons():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert app.checks_tab.selected.check_id == "cue_player"
            assert _plain(app, "#checks-detail-head") == "! sounds · warning"
            body = _plain(app, "#checks-detail-body")
            assert "The sound pack bravo has no charlie cue." in body
            assert "pack bravo · 1 cue missing" in body
            assert _plain(app, "#checks-detail-path") == "checked 13:21 · /tmp/sounds/bravo"
            labels = [
                str(_button(app, selector).label)
                for selector in ("#checks-fix", "#checks-test", "#checks-log", "#checks-copy")
            ]
            assert labels == [
                "[f] Fix: choose a sound pack",
                "[t] Test: play cues",
                "[l] Open log",
                "[c] Copy report",
            ]
            assert all(_button(app, f"#checks-{name}").display for name in ("fix", "test"))
            dialogs = [
                str(_button(app, selector).label)
                for selector in ("#checks-quick", "#checks-models", "#checks-defaults")
            ]
            assert dialogs == ["[Q] Quick setup…", "[m] Models…", "[D] Defaults…"]
            assert not app.screen.query("#checks-run"), "Run again is in the context card"
            frame = app.screen.query_one("#checks-detail").content_region
            for name in ("fix", "test", "log", "copy", "quick", "models", "defaults"):
                region = _button(app, f"#checks-{name}").region
                assert frame.contains_region(region), f"{name} is cut at 150 x 45"
            assert _plain(app, "#checks-warnings-title") == "recent warnings (no transcript text)"

            # A passing check without a path or a test: no fix, no test, no path.
            app.checks_tab.select_check("system_service")
            await pilot.pause()
            assert _plain(app, "#checks-detail-head") == "✓ system service · pass"
            assert _plain(app, "#checks-detail-path") == "checked 13:21"
            assert not _button(app, "#checks-fix").display
            assert _button(app, "#checks-test").display
            app.checks_tab.select_check("ffmpeg")
            await pilot.pause()
            assert _plain(app, "#checks-detail-head") == f"{FAIL} ffmpeg · failure"
            assert not _button(app, "#checks-test").display

    asyncio.run(exercise())


def test_checks_enter_shows_the_fix_hint_and_keys_move_in_group_order():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert "Choose another sound pack." not in _plain(app, "#checks-detail-body")
            await pilot.press("enter")
            assert "how to fix: Choose another sound pack." in _plain(app, "#checks-detail-body")
            order = []
            for _ in range(len(app.checks_tab.report.checks)):
                await pilot.press("down")
                order.append(app.checks_tab.selected.label)
            assert order == [
                "speech model",
                "voice models",
                "system service",
                "ffmpeg",
                "input access",
                "microphone",
                "hotkey",
                "sounds",
            ]
            await pilot.press("up")
            assert app.checks_tab.selected.label == "hotkey"
            assert _plain(app, "#checks-input").splitlines()[2].startswith("▶ ✓ hotkey")

    asyncio.run(exercise())


def test_checks_click_on_a_row_selects_that_check():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.click("#checks-engine", offset=(4, 1))
            await pilot.pause()
            assert app.checks_tab.selected.label == "voice models"
            assert _plain(app, "#checks-detail-head") == "✓ voice models · pass"
            assert app.current_mode == "settings"

    asyncio.run(exercise())


def test_checks_card_badge_and_tab_label_follow_the_last_run():
    async def exercise():
        app = _app()
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            card = app.screen.query_one("#sidebar-card", Static).render()
            assert app.screen.query_one("#sidebar-context").border_title == "checks"
            ran_at = app.checks_tab.ran_at
            assert card.plain == f"6 pass · 1 warn · 1 fail\nlast run {ran_at:%H:%M}"
            ok = card.get_style_at_offset(0)
            assert ok.rich_style.color.get_truecolor() == Color.parse("#6ee69a").get_truecolor()
            zero = card.get_style_at_offset(card.plain.index("1 fail"))
            assert zero.rich_style.color is not None

            nav = app.screen.query_one("#sidebar", Static).render().plain.splitlines()
            assert nav[2].endswith("1 F")
            assert str(_button(app, "#tab-checks").label) == "▶ Checks ●2"

    asyncio.run(exercise())


def test_checks_slow_run_leaves_the_app_answering_keys():
    release = threading.Event()
    started = threading.Event()

    def slow_probe(_config, _path):
        started.set()
        release.wait(5)
        return _board_report()

    async def exercise():
        app = _app(doctor_probe=slow_probe)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3", "left")
            await _settle(pilot, started.is_set)
            assert "Checking" in _plain(app, "#checks-input")
            await pilot.press("1")
            await pilot.pause()
            assert app.current_mode == "record"
            await pilot.press("3")
            await pilot.pause()
            assert app.current_mode == "settings"
            assert app.checks_tab.report is None
            release.set()
            await _settle(pilot, lambda: app.checks_tab.report is not None)
            await pilot.pause()
            assert "input access" in _plain(app, "#checks-input")

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_checks_run_again_replaces_the_results():
    reports = [
        _board_report(),
        DoctorReport((_check("has_mic", "microphone", "input", "fail", "no device", "x"),), ()),
    ]
    calls = []

    def probe(_config, _path):
        calls.append("probe")
        return reports[len(calls) - 1]

    async def exercise():
        app = _app(doctor_probe=probe)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            first = app.checks_tab.report
            await pilot.press("r")
            await _settle(pilot, lambda: app.checks_tab.report is not first)
            await pilot.pause()
            assert calls == ["probe", "probe"]
            assert _plain(app, "#checks-input").splitlines() == [
                _plain(app, "#checks-input").splitlines()[0]
            ]
            assert f"{FAIL} microphone" in _plain(app, "#checks-input")
            assert not app.screen.query_one("#checks-section-engine").display
            card_text = app.screen.query_one("#sidebar-card", Static).render()
            card = card_text.plain
            assert card.startswith("0 pass · 0 warn · 1 fail\n")
            assert card_text.get_style_at_offset(0).rich_style.color is None, "a zero count"

            assert str(_button(app, "#tab-checks").label) == "▶ Checks ●1"

    asyncio.run(exercise())


def test_checks_card_run_again_button_starts_a_new_run():
    calls = []

    def probe(_config, _path):
        calls.append("probe")
        return _board_report()

    async def exercise():
        app = _app(doctor_probe=probe)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            first = app.checks_tab.report
            card = app.screen.query_one("#sidebar-context")
            button = card.query_one("#card-r", HubButton)
            assert str(button.label) == "[r] Run again"
            assert card.content_region.contains_region(button.region)
            assert await pilot.click(button)
            await _settle(pilot, lambda: app.checks_tab.report is not first)
            assert calls == ["probe", "probe"]

            await pilot.press("1")
            await pilot.pause()
            record_buttons = app.screen.query_one("#sidebar-context").query(HubButton)
            assert "[r] Run again" not in [str(b.label) for b in record_buttons]

    asyncio.run(exercise())


# V2: fix and test


@pytest.mark.parametrize(
    ("check_id", "expected"),
    [
        ("key_injector_ok", QuickSetupDialog),
        ("has_mic", ("audio", "audio.input_device")),
        ("hotkey_access_ok", ("general", "hotkey.binding")),
        ("cue_player", ("general", "feedback.sound_pack")),
        ("model_cached", ModelsDialog),
        ("live_models_cached", ModelsDialog),
        ("refine_service", ("recognition", "refine.host")),
        ("overlay", ("general", "feedback.overlay")),
        ("clipboard_restore", ("general", "delivery.restore_clipboard")),
    ],
)
def test_checks_fix_opens_the_setting_row_or_the_dialog(tmp_path, check_id, expected):
    path = tmp_path / "config.toml"
    path.write_text(default_toml(), encoding="utf-8")
    report = DoctorReport((_check(check_id, check_id, "engine", "warn", "x", "y"),), ())

    async def exercise():
        app = _app(report, config_editor=ConfigEditor(path), model_status=lambda: ())
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert _button(app, "#checks-fix").display
            await pilot.press("f")
            await pilot.pause()
            if isinstance(expected, tuple):
                tab, key = expected
                assert app.current_mode == "settings"
                assert app.settings_screen.tab == tab
                assert app.config_editor.selected_key == key
            else:
                assert isinstance(app.screen, expected)

    asyncio.run(exercise())


def test_checks_fix_click_runs_the_same_fix_as_the_key(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(default_toml(), encoding="utf-8")

    async def exercise():
        app = _app(config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.click("#checks-fix")
            await pilot.pause()
            assert app.settings_screen.tab == "general"
            assert app.config_editor.selected_key == "feedback.sound_pack"

    asyncio.run(exercise())


def test_checks_fix_without_a_target_shows_the_hint_in_a_notice():
    notices = []

    async def exercise():
        app = _app()
        app.notify = lambda message, **_kwargs: notices.append(message)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            app.checks_tab.select_check("ffmpeg")
            await pilot.pause()
            assert not _button(app, "#checks-fix").display
            await pilot.press("f")
            assert notices == ["Install it."]
            assert app.settings_screen.tab == "checks"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("check_id", "area", "label"),
    [
        ("key_injector_ok", "input_access", "check access"),
        ("has_mic", "microphone", "list devices"),
        ("hotkey_access_ok", "hotkey", "check binding"),
        ("cue_player", "sounds", "play cues"),
        ("model_cached", "models", "model files"),
        ("live_models_cached", "models", "model files"),
        ("system_service", "system_service", "service state"),
    ],
)
def test_checks_test_runs_the_setup_test_of_the_area(check_id, area, label):
    report = DoctorReport((_check(check_id, check_id, "input", "warn", "x", "y"),), ())
    areas = []

    def setup_test(step, _config):
        areas.append(step)
        return f"tested {step}"

    async def exercise():
        app = _app(report, setup_test=setup_test)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            assert str(_button(app, "#checks-test").label) == f"[t] Test: {label}"
            await pilot.press("t")
            await _settle(pilot, lambda: app.checks_tab.test_status)
            await pilot.pause()
            assert areas == [area]
            assert _plain(app, "#checks-test-status") == f"test: tested {area}"

    asyncio.run(exercise())


def test_checks_microphone_test_lists_devices_and_never_captures(monkeypatch):
    import sounddevice

    def no_capture(*_args, **_kwargs):
        raise AssertionError("the microphone test opened an audio stream")

    for name in ("InputStream", "RawInputStream", "Stream", "rec"):
        monkeypatch.setattr(sounddevice, name, no_capture)
    monkeypatch.setattr(
        sounddevice,
        "query_devices",
        lambda: (
            {"name": "alpha mic", "max_input_channels": 1},
            {"name": "bravo speaker", "max_input_channels": 0},
            {"name": "charlie mic", "max_input_channels": 2},
        ),
    )
    monkeypatch.setattr(sounddevice, "default", SimpleNamespace(device=(0, 1)))
    report = DoctorReport((_check("has_mic", "microphone", "input"),), ())

    async def exercise():
        app = _app(report)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("t")
            await _settle(pilot, lambda: app.checks_tab.test_status)
            await pilot.pause()
            assert _plain(app, "#checks-test-status") == (
                "test: 2 input devices: 0: alpha mic, 2: charlie mic; no audio was captured"
            )

    asyncio.run(exercise())


def test_checks_sounds_test_plays_the_preview_through_the_preview_path(monkeypatch, tmp_path):
    from stenographer.lib import platform as platform_module
    from stenographer.lib.sounds import packs, playback

    played = []
    pack = object()
    player = object()
    monkeypatch.setattr(packs, "load_sound_pack", lambda name, _dir: pack if name else None)
    real_platform = platform_module.current_platform

    class CuePlatform:
        """The real platform with a fake cue player."""

        def __init__(self):
            self._real = real_platform()

        def cue_player(self):
            return player

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(platform_module, "current_platform", CuePlatform)
    monkeypatch.setattr(
        playback,
        "preview_sound_pack",
        lambda *args: played.append(args),
    )
    path = tmp_path / "config.toml"
    path.write_text(default_toml(), encoding="utf-8")
    report = DoctorReport((_check("cue_player", "sounds", "input"),), ())

    async def exercise():
        app = _app(report, config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("t")
            await _settle(pilot, lambda: app.checks_tab.test_status)
            config = app.current_config()
            assert played == [(pack, player, playback.preview_volume(config.feedback))]
            assert app.checks_tab.test_status == (
                f"Played the {config.feedback.sound_pack} sound preview"
            )

    asyncio.run(exercise())


def test_checks_open_log_calls_the_opener_with_the_log_path():
    from stenographer.lib.logging.pipeline import log_paths

    opened = []

    async def exercise():
        app = _app(open_log=lambda path: opened.append(path) or True)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("l")
            await pilot.click("#checks-log")
            await pilot.pause()

    asyncio.run(exercise())
    assert opened == [log_paths()[0], log_paths()[0]]


def test_checks_copy_report_puts_the_report_on_the_clipboard():
    clipboard = []
    warnings = ("13:03:10 WARN live: system_source_failed", "10:41:00 ERROR alpha: bravo")

    async def exercise():
        app = _app(_board_report(warnings), copy_report=clipboard.append)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("c")
            await pilot.pause()

    asyncio.run(exercise())
    assert len(clipboard) == 1
    report = clipboard[0]
    assert report.startswith("Checks report: 6 pass, 1 warn, 1 fail\n")
    assert "\ninput\n" in report
    assert "WARN sounds: pack bravo · 1 cue missing" in report
    assert "FAIL ffmpeg: ffmpeg is not installed" in report
    assert "\nRecent warnings (no transcript text)\n" in report
    assert "13:03  WARN   live: system_source_failed" in report
    assert "       System audio stopped; the mic went on recording." in report
    assert "10:41  ERROR  alpha: bravo" in report


# V2: recent warnings (D16)


def _write_private_log(path) -> None:
    """Write a real log file in the pipeline format with the marker in each free field."""
    from stenographer.lib.logging import pipeline

    logger = logging.getLogger("stenographer.test_checks_privacy")
    logger.propagate = False
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(pipeline._FORMAT, defaults=pipeline._FORMAT_DEFAULTS))
    logger.addHandler(handler)
    try:
        logger.warning(f"live: system_source_failed {MARKER} in the message body")
        logger.warning(fmt_event("files", "refine_timeout", note=MARKER))
        try:
            raise RuntimeError(f"exception text {MARKER}")
        except RuntimeError as exc:
            log_failure(logger, logging.ERROR, "hub: setup_test_failed", exc, safe=True)
            logger.exception("worker: request_timeout")
        logger.warning(f"{MARKER} with no event token")
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert path.read_text(encoding="utf-8").count(MARKER) >= 4


def test_checks_recent_warnings_never_show_a_message_exception_or_field(tmp_path):
    log = tmp_path / "stenographer.log"
    _write_private_log(log)
    report = DoctorReport((_check("has_mic", "microphone", "input"),), recent_warnings((log,)))
    clipboard = []

    async def exercise():
        app = _app(report, copy_report=clipboard.append)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            shown = _plain(app, "#checks-warnings")
            assert MARKER not in shown
            rows = shown.splitlines()
            live = next(i for i, row in enumerate(rows) if "live: system_source_failed" in row)
            assert rows[live].endswith("WARN   live: system_source_failed")
            assert rows[live + 1] == ("       System audio stopped; the mic went on recording.")
            assert "files: refine_timeout" in shown
            assert "hub: setup_test_failed" in shown
            assert "worker: request_timeout" in shown
            await pilot.press("c")
            await pilot.pause()

    asyncio.run(exercise())
    assert MARKER not in clipboard[0]
    assert "hub: setup_test_failed" in clipboard[0]


def test_checks_warning_levels_have_a_word_and_a_colour():
    warnings = ("21:11:37 WARN overlay: helper_restarting", "21:10:03 ERROR audio: device_lost")

    async def exercise():
        app = _app(_board_report(warnings))
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            text = app.screen.query_one("#checks-warnings", Static).render()
            assert "21:11  WARN   overlay: helper_restarting" in text.plain
            assert "21:10  ERROR  audio: device_lost" in text.plain
            for word, tone in (("WARN", "#ffaf5f"), ("ERROR", "#ff875f")):
                style = text.get_style_at_offset(text.plain.index(word))
                assert style.rich_style.color.get_truecolor() == Color.parse(tone).get_truecolor()

    asyncio.run(exercise())


# V2: dialogs


def test_checks_quick_setup_tests_edits_and_closes(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(default_toml(), encoding="utf-8")
    areas = []

    def setup_test(step, _config):
        areas.append(step)
        return f"tested {step}"

    async def exercise():
        app = _app(config_editor=ConfigEditor(path), setup_test=setup_test)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("shift+q")
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, QuickSetupDialog)
            steps = dialog.query_one("#quick-setup-steps", Static).render().plain.splitlines()
            assert [row[4:].split("  ")[0] for row in steps] == [
                "input access",
                "microphone",
                "hotkey",
            ]
            assert steps[0].startswith("▶ ✓ input access")
            await pilot.press("t")
            await _settle(pilot, lambda: areas)
            await pilot.pause()
            assert "test: tested input_access" in _plain(app, "#quick-setup-detail")
            await pilot.press("down", "down", "t")
            await _settle(pilot, lambda: len(areas) == 2)
            assert areas == ["input_access", "hotkey"]

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, QuickSetupDialog)
            assert app.settings_screen.tab == "checks"

            await pilot.click("#checks-quick")
            await pilot.pause()
            assert isinstance(app.screen, QuickSetupDialog)
            await pilot.press("down", "e")
            await pilot.pause()
            assert not isinstance(app.screen, QuickSetupDialog)
            assert app.settings_screen.tab == "audio"
            assert app.config_editor.selected_key == "audio.input_device"

    asyncio.run(exercise())


def test_checks_models_dialog_shows_each_model_and_downloads_after_confirmation():
    present = {"asr": False, "vad": True, "speaker": False}
    downloads = []

    def model_status():
        return (
            ModelEntry("asr", "speech model", "alpha model", present["asr"], "about 1 GB"),
            ModelEntry("vad", "voice activity", "bravo.onnx", present["vad"], "2 MB"),
            ModelEntry("speaker", "speaker model", "charlie.onnx", present["speaker"], "40 MB"),
        )

    def model_download(model_id):
        downloads.append(model_id)
        present[model_id] = True

    async def exercise():
        app = _app(model_status=model_status, model_download=model_download)
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, ModelsDialog)
            rows = _plain(app, "#models-list").splitlines()
            assert rows[0].startswith("▶ speech model · alpha model")
            assert rows[0].endswith(f"{FAIL} missing")
            assert rows[1].endswith("✓ present")
            assert rows[2].endswith(f"{FAIL} missing")

            await pilot.press("enter")
            await pilot.pause()
            prompt = _plain(app, "#quit-prompt")
            assert prompt == "Download speech model alpha model now? (about 1 GB)"
            await pilot.press("n")
            await pilot.pause()
            assert downloads == []
            assert isinstance(app.screen, ModelsDialog)

            await pilot.press("enter", "y")
            await _settle(pilot, lambda: downloads == ["asr"])
            await _settle(
                pilot, lambda: _plain(app, "#models-list").splitlines()[0].endswith("✓ present")
            )

            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ModelsDialog), "a present model asks nothing"
            assert downloads == ["asr"]

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ModelsDialog)

    asyncio.run(exercise())


def test_checks_default_model_download_fetches_only_the_chosen_model(monkeypatch, tmp_path):
    from stenographer.cli.hub import doctor_view
    from stenographer.lib.live import download as live_download
    from stenographer.lib.transcribe import bark_download

    calls = []
    monkeypatch.setattr(bark_download, "download_bark_pro", lambda data_dir: calls.append("asr"))
    monkeypatch.setattr(
        live_download,
        "download_live_models",
        lambda data_dir, models: calls.append(tuple(m.filename for m in models)),
    )

    doctor_view.default_model_download("asr")
    doctor_view.default_model_download("vad")
    doctor_view.default_model_download("speaker")

    assert calls == ["asr", ("silero_vad.onnx",), ("nemo_en_titanet_small.onnx",)]
    entries = doctor_view.default_model_status()
    assert [(entry.model_id, entry.present) for entry in entries] == [
        ("asr", False),
        ("vad", False),
        ("speaker", False),
    ]


def test_checks_defaults_dialog_writes_defaults_with_a_backup_or_cancels(tmp_path):
    path = tmp_path / "config.toml"
    defaults = Config.defaults()
    changed = dataclasses.replace(
        defaults, audio=dataclasses.replace(defaults.audio, input_device="alpha microphone")
    )
    ConfigDocument.defaults(path).save(changed)
    original = path.read_bytes()

    async def exercise():
        app = _app(config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await _open_checks(pilot)
            await pilot.press("shift+d")
            await pilot.pause()
            assert isinstance(app.screen, DefaultsDialog)
            message = _plain(app, "#defaults-message")
            assert str(path) in message
            assert "backup" in message
            await pilot.press("escape")
            await pilot.pause()
            assert path.read_bytes() == original
            assert not tuple(tmp_path.glob("config.toml.bak-*"))

            await pilot.click("#checks-defaults")
            await pilot.pause()
            assert isinstance(app.screen, DefaultsDialog)
            await pilot.press("y")
            await _settle(pilot, lambda: path.read_bytes() != original)
            await pilot.pause()

    asyncio.run(exercise())
    assert Config.loads(path.read_text()) == defaults
    backups = tuple(tmp_path.glob("config.toml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_checks_settings_quit_prompts_to_save_draft_changes(tmp_path):
    async def exercise():
        path = tmp_path / "config.toml"
        editor = ConfigEditor(path)
        editor.edit("audio.input_device", "alpha microphone")
        app = _app(DoctorReport((), ()), config_editor=editor)
        async with app.run_test() as pilot:
            await _open_checks(pilot)
            await pilot.press("q")
            prompt = str(app.screen.query_one("#config-prompt-message", Static).render()).casefold()
            assert "save or discard" in prompt
            await pilot.click("#choice-save")

        assert Config.loads(path.read_text()).audio.input_device == "alpha microphone"

    asyncio.run(exercise())


# Check data


def test_checks_safe_warning_lines_only_keep_warning_event_names():
    text = "\n".join(
        (
            "2026-10-20 12:00:00,001 INFO stenographer.daemon daemon: started",
            "2026-10-20 12:00:01,001 WARNING stenographer.asr utt=7 "
            f"asr: retry transcript={MARKER}",
            f"2026-10-20 12:00:02,001 ERROR stenographer.audio audio: failed text={MARKER}",
            "2026-10-20 12:00:03,001 WARNING stenographer.misc user dictated private words",
        )
    )

    warnings = safe_warning_lines(text)

    assert warnings == ("12:00:01 WARN asr: retry", "12:00:02 ERROR audio: failed")
    assert "stenographer.asr" not in "\n".join(warnings)
    assert MARKER not in "\n".join(warnings)


def test_checks_recent_warnings_read_logs_and_omit_message_fields(tmp_path):
    path = tmp_path / "stenographer.log"
    line = "2026-10-20 12:00:01,001 WARNING stenographer.asr "
    path.write_text(line + f"asr: retry transcript={MARKER}\n")

    warnings = recent_warnings((path,))

    assert warnings == ("12:00:01 WARN asr: retry",)
    assert MARKER not in "\n".join(warnings)


@pytest.mark.parametrize("refine_bytes", [4_000_000_000, None])
def test_checks_build_report_groups_fake_host_checks_and_counts_warnings(
    monkeypatch, tmp_path, refine_bytes
):
    from stenographer.cli.hub import doctor_view
    from stenographer.cli.shared.capabilities import Capabilities
    from stenographer.lib import platform as platform_module
    from stenographer.lib.diagnostics import additional_checks
    from stenographer.lib.diagnostics.additional_checks import DiagnosticCheck
    from stenographer.lib.logging import pipeline as logging_pipeline
    from stenographer.lib.refine import client as refine_client
    from stenographer.overlay import platform as overlay_platform
    from stenographer.overlay.capabilities.models import OverlayCapability
    from stenographer.overlay.platform.guidance import OverlayGuidance
    from stenographer.overlay.protocol.unavailablereason import UnavailableReason

    guidance = SimpleNamespace(
        capability_labels={},
        capability_fix_hints={"hotkey_access_ok": "Join the input group."},
        clipboard_fix_hints={},
        clipboard_fix_hint_default="Install clipboard support.",
        clipboard_read_fix_hints={"test": "Enable clipboard reads."},
        service_noun="systemd unit",
        service_installer="scripts/install.sh",
        service_unknown_detail="service manager is unavailable",
        service_start_command="systemctl --user start stenographer.service",
    )
    overlay_guidance = OverlayGuidance(
        overlay_backend_labels={},
        overlay_fix_hints={UnavailableReason.NO_X_DISPLAY: "Enable XWayland."},
        overlay_fix_hint_default="Check the display.",
    )
    caps = Capabilities(
        key_injector_ok=True,
        hotkey_access_ok=False,
        has_mic=True,
        model_cached=True,
        clipboard_ok=True,
        clipboard_backend="test",
        clipboard_read_ok=False,
        cue_player=None,
        service_enabled=None,
        service_active="inactive",
        overlay=OverlayCapability.unavailable(UnavailableReason.NO_X_DISPLAY),
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr("stenographer.cli.shared.capability_probe.probe", lambda _config: caps)
    monkeypatch.setattr(
        platform_module,
        "current_platform",
        lambda: SimpleNamespace(guidance=lambda: guidance, data_dir=lambda _env, _home: data_dir),
    )
    monkeypatch.setattr(
        overlay_platform,
        "current_platform",
        lambda: SimpleNamespace(guidance=lambda: overlay_guidance),
    )
    monkeypatch.setattr(
        additional_checks,
        "collect_additional_checks",
        lambda: (
            DiagnosticCheck("system_capture", "warn", "no default sink", "Select a sink."),
            DiagnosticCheck("live_models_cached", "ok", "cached", ""),
            DiagnosticCheck("ffmpeg", "warn", "not installed", "Install ffmpeg."),
        ),
    )
    hosts = []
    monkeypatch.setattr(
        refine_client,
        "installed_model_bytes",
        lambda host, model: hosts.append((host, model)) or refine_bytes,
    )
    monkeypatch.setattr(
        logging_pipeline,
        "log_paths",
        lambda: (tmp_path / "stenographer.log", tmp_path / "overlay.log"),
    )
    config = Config.defaults()

    report = doctor_view.build_report(config, tmp_path / "config.toml").in_group_order()
    checks = {check.check_id: check for check in report.checks}

    assert [(check.group, check.label) for check in report.checks] == [
        ("input", "input access"),
        ("input", "microphone"),
        ("input", "hotkey"),
        ("input", "sounds"),
        ("engine", "speech model"),
        ("engine", "voice models"),
        ("engine", "refine service"),
        ("engine", "system audio"),
        ("engine", "system service"),
        ("other", "ffmpeg"),
        ("other", "clipboard · test"),
        ("other", "overlay"),
        ("other", "clipboard restore"),
    ]
    assert all(check.explanation for check in report.checks)
    assert checks["hotkey_access_ok"].status == "fail"
    assert checks["hotkey_access_ok"].fix == "Join the input group."
    assert checks["model_cached"].detail == "Underdog Bark 3.0 Pro"
    assert checks["model_cached"].path.startswith(str(data_dir))
    assert checks["live_models_cached"].path == str(data_dir / "models" / "live")
    assert checks["system_capture"].status == "warn"
    assert checks["overlay"].fix == "Enable XWayland."
    assert checks["clipboard_restore"].fix == "Enable clipboard reads."
    assert hosts == [(config.refine.host, config.refine.model)]
    refine = checks["refine_service"]
    assert refine.detail.startswith(f"127.0.0.1 · {config.refine.model}")
    if refine_bytes is None:
        assert refine.status == "warn"
        assert refine.detail.endswith("not found")
        assert report.warn_count == 7
    else:
        assert refine.status == "ok"
        assert report.warn_count == 6
    assert report.fail_count == 1


def test_checks_refine_service_check_asks_nothing_when_refine_is_off(monkeypatch):
    from stenographer.cli.hub import doctor_view
    from stenographer.lib.refine import client as refine_client

    def no_request(*_args, **_kwargs):
        raise AssertionError("a disabled refine service was asked")

    monkeypatch.setattr(refine_client, "installed_model_bytes", no_request)
    defaults = Config.defaults()
    config = dataclasses.replace(
        defaults, refine=dataclasses.replace(defaults.refine, enabled=False)
    )

    check = doctor_view._refine_check(config)

    assert (check.status, check.detail) == ("ok", "off")


def test_checks_models_step_probes_the_installed_bark_model(monkeypatch, tmp_path):
    # The root conftest does not redirect XDG_DATA_HOME; never touch the real one.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    import json
    import os
    from pathlib import Path

    from stenographer.cli.hub.setup_test import test_step
    from stenographer.lib.platform import current_platform
    from stenographer.lib.transcribe import bark_download
    from stenographer.lib.transcribe.bark_pins import BARK_PRO_PINS

    config = Config.defaults()
    assert test_step("models", config, tmp_path).startswith("ASR model not cached")

    root = bark_download.model_dir(current_platform().data_dir(os.environ, Path.home()))
    root.mkdir(parents=True)
    hashes = {name: "0" * 64 for name in bark_download.CONVERTED_FILES}
    for name in hashes:
        (root / name).write_bytes(b"")
    manifest = bark_download.build_manifest(BARK_PRO_PINS, hashes)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert test_step("models", config, tmp_path).startswith("ASR model cached")
