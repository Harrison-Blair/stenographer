# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the hub shell: navigation, sidebar, badges and shell contracts."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import pytest
from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.choice_dialog import ChoiceDialog
from stenographer.cli.hub.config_view import ConfigEditor
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
from stenographer.cli.hub.engine_status import EngineStatus
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config
from tests.cli.hub.test_library import FakeServices as LibraryServices
from tests.cli.hub.test_library import _write_rec as _write_session
from tests.cli.hub.test_live_view import FakeServices as RecordingServices


class IdleServices:
    recording = False
    files_running = False
    session = None


class FakeSampler:
    """Stand in for the process counters: the test sets the next snapshot."""

    def __init__(self, status: EngineStatus):
        self.status = status
        self.samples = 0

    def sample(self) -> None:
        self.samples += 1

    def snapshot(self) -> EngineStatus:
        return self.status


def _report(*statuses: str) -> DoctorReport:
    return DoctorReport(
        tuple(
            DoctorCheck(f"check-{index}", f"check {index}", "input and audio", status, "", "")
            for index, status in enumerate(statuses)
        ),
        (),
    )


def _nav_rows(app: HubApp) -> list[str]:
    return str(app.screen.query_one("#sidebar", Static).render()).splitlines()


def _config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(default_toml(), encoding="utf-8")
    return path


def _prompt_text(app: HubApp) -> str:
    return str(app.screen.query_one("#config-prompt-message", Static).render())


def test_shell_number_keys_show_screens_and_four_to_six_are_unbound():
    async def exercise():
        app = HubApp(IdleServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            assert app.current_mode == "record"
            assert _nav_rows(app)[0].startswith("▶ 1 Record")
            for key, screen, row in (("2", "library", 1), ("3", "settings", 2), ("1", "record", 0)):
                await pilot.press(key)
                await pilot.pause()
                assert app.current_mode == screen
                assert _nav_rows(app)[row].startswith("▶ ")
            for key in "456":
                await pilot.press(key)
                assert app.current_mode == "record"
            assert not {"4", "5", "6"} & set(app.screen.active_bindings)

    asyncio.run(exercise())


def test_shell_nav_row_click_shows_the_screen():
    async def exercise():
        app = HubApp(IdleServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            for row, screen in ((1, "library"), (2, "settings"), (0, "record")):
                assert await pilot.click("#sidebar", offset=(4, row))
                await pilot.pause()
                assert app.current_mode == screen

    asyncio.run(exercise())


def test_shell_nav_badges_show_recording_paused_entries_and_check_results(tmp_path):
    async def exercise():
        services = RecordingServices()
        app = HubApp(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            assert _nav_rows(app)[0].endswith("● 00:00:03")
            services.session.paused = True
            app.refresh_view()
            assert _nav_rows(app)[0].endswith("Ⅱ 00:00:03")
            services.recording = False
            app.refresh_view()
            assert _nav_rows(app)[0].split() == ["▶", "1", "Record"]

            assert _nav_rows(app)[2].split() == ["3", "Settings"]
            now = datetime(2026, 10, 27, 13, 3, tzinfo=UTC)
            app.set_check_summary(5, 0, 0, now)
            assert _nav_rows(app)[2].split() == ["3", "Settings"]
            app.set_check_summary(3, 2, 0, now)
            assert _nav_rows(app)[2].endswith("2 W")
            app.set_check_summary(3, 2, 1, now)
            assert _nav_rows(app)[2].endswith("1 F")

        sessions_root = tmp_path / "sessions"
        _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
        _write_session(sessions_root, datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
        library = HubApp(LibraryServices(sessions_root))
        async with library.run_test(size=(150, 45)) as pilot:
            for _ in range(50):
                if library.library_screen.entry_count is not None:
                    break
                await pilot.pause(0.02)
            library.refresh_view()
            assert _nav_rows(library)[1].split() == ["2", "Library", "2"]

    asyncio.run(exercise())


def test_shell_nav_badges_end_at_the_right_edge_on_each_screen(tmp_path):
    async def exercise():
        sessions_root = tmp_path / "sessions"
        _write_session(sessions_root, datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
        app = HubApp(LibraryServices(sessions_root))
        async with app.run_test(size=(150, 45)) as pilot:
            for key in ("1", "2", "3", "2"):
                await pilot.press(key)
                await pilot.pause(0.1)
                nav = app.screen.query_one("#sidebar", Static)
                library_row = _nav_rows(app)[1]
                assert library_row.split()[-1] == "1"
                assert len(library_row) == nav.size.width, (key, library_row)

    asyncio.run(exercise())


def test_shell_sidebar_engine_card_draws_the_sampler_snapshot_each_second():
    async def exercise():
        sampler = FakeSampler(
            EngineStatus("bark-pro-int8", "idle · unloaded", None, None, None, ())
        )
        app = HubApp(IdleServices(), engine_sampler=sampler)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()

            def card() -> list[str]:
                return [
                    str(app.screen.query_one(f"#{name}", Static).render())
                    for name in (
                        "engine-model",
                        "engine-state",
                        "engine-cpu-app",
                        "engine-cpu-all",
                        "engine-ram-app",
                        "engine-history",
                    )
                ]

            assert card() == [
                "bark-pro-int8",
                "idle · unloaded",
                "cpu app      — ▕········▏",
                "    all      — ▕········▏",
                "ram app      —",
                "···················· 60 s",
            ]
            samples = sampler.samples
            sampler.status = EngineStatus(
                "bark-pro-int8", "ready · 2 queued", 50.0, 25.0, 1_610_612_736, (0.0, 100.0)
            )
            await pilot.pause(1.2)
            assert sampler.samples > samples
            assert card() == [
                "bark-pro-int8",
                "ready · 2 queued",
                "cpu app    50% ▕████····▏",
                "    all    25% ▕██······▏",
                "ram app 1.5 GB",
                "▁█·················· 60 s",
            ]

    asyncio.run(exercise())


def test_shell_show_screen_and_set_context_card_follow_the_screen():
    async def exercise():
        app = HubApp(IdleServices())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            app.show_screen("settings")
            await pilot.pause()
            assert app.current_mode == "settings"
            app.set_context_card("library", "library card", title="storage")
            card = app.screen.query_one("#sidebar-card", Static)
            assert "library card" not in str(card.render())
            with pytest.raises(ValueError):
                app.show_screen("files")

    asyncio.run(exercise())


def test_shell_show_library_selects_listed_unloaded_and_unknown_sessions(tmp_path):
    async def exercise():
        sessions_root = tmp_path / "sessions"
        older = _write_session(sessions_root, datetime(2026, 10, 20, 1, 12, 18, tzinfo=UTC))
        latest = _write_session(sessions_root, datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
        app = HubApp(LibraryServices(sessions_root))
        panel = app.library_screen

        async def until(condition) -> None:
            for _ in range(100):
                if condition():
                    return
                await pilot.pause(0.02)
            raise AssertionError("condition not met")

        async with app.run_test(size=(150, 45)) as pilot:
            await until(lambda: len(panel.summaries) == 2)
            assert panel.selected_id == latest.name

            app.show_library(older.name)
            await pilot.pause()
            assert app.current_mode == "library"
            assert panel.selected_id == older.name

            # A session saved after the list loaded is not listed yet: reload and select it.
            newest = _write_session(sessions_root, datetime(2026, 10, 22, 8, 0, tzinfo=UTC))
            app.show_screen("record")
            app.show_library(newest.name)
            await until(lambda: panel.selected_id == newest.name)
            assert len(panel.summaries) == 3

            app.show_library(older.name)
            await until(lambda: panel.selected_id == older.name)
            app.show_library("20990101T000000Z")
            await until(lambda: any("not found" in n.message for n in app._notifications))
            assert panel.selected_id == older.name
            notice = next(n for n in app._notifications if "not found" in n.message)
            assert notice.severity == "warning"

    asyncio.run(exercise())


def test_shell_open_setting_selects_tab_and_row_and_keeps_unsaved_changes(tmp_path):
    async def exercise():
        app = HubApp(IdleServices(), config_path=_config_path(tmp_path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            app.config_editor.edit("hotkey.binding", "KEY_F9")
            app.open_setting("asr.cpu_threads")
            await pilot.pause()
            assert app.current_mode == "settings"
            assert app.settings_screen.tab == "recognition"
            assert app.config_editor.selected_key == "asr.cpu_threads"
            assert app.config_editor.config.hotkey.binding == "KEY_F9"
            assert not app.screen.query("#config-prompt-message")

            app.open_setting("live.diarize_mic")
            await pilot.pause()
            assert app.settings_screen.tab == "live"
            assert app.config_editor.selected_key == "live.diarize_mic"
            assert app.config_editor.dirty

            await pilot.press("left", "left")
            assert app.settings_screen.tab == "audio"
            assert app.config_editor.dirty
            assert not app.screen.query("#config-prompt-message")

    asyncio.run(exercise())


def test_shell_set_check_summary_sets_badge_checks_tab_label_and_checks_card():
    async def exercise():
        app = HubApp(IdleServices(), doctor_probe=lambda _config, _path: _report("ok", "warn"))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            app.set_check_summary(4, 2, 1, datetime(2026, 10, 27, 13, 3))
            assert _nav_rows(app)[2].endswith("1 F")
            assert str(app.screen.query_one("#tab-checks").label) == "  Checks ●3"
            await pilot.pause()
            tab = app.screen.query_one("#tab-checks")
            assert tab.content_size.width >= len("  Checks ●3"), "the tab grows with its label"

            await pilot.press("left")
            await pilot.pause()
            card = app.screen.query_one("#sidebar-card", Static).render().plain
            assert app.screen.query_one("#sidebar-context").border_title == "checks"
            assert card.startswith("1 pass · 1 warn · 0 fail\nlast run ")
            assert _nav_rows(app)[2].endswith("1 W")
            assert str(app.screen.query_one("#tab-checks").label) == "▶ Checks ●1"

    asyncio.run(exercise())


def test_shell_session_busy_registry_admits_one_owner_across_threads():
    app = HubApp(IdleServices())
    threads = 16
    barrier = threading.Barrier(threads)
    results: list[bool] = []
    lock = threading.Lock()

    def contend(owner: str) -> None:
        barrier.wait()
        acquired = app.try_acquire_session("20261020T011218Z", owner)
        with lock:
            results.append(acquired)

    workers = [threading.Thread(target=contend, args=(f"owner-{n}",)) for n in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert sorted(results) == [False] * (threads - 1) + [True]
    assert app.is_busy("20261020T011218Z")


def test_shell_session_release_needs_the_owner():
    app = HubApp(IdleServices())
    assert not app.is_busy("a")
    assert app.try_acquire_session("a", "relabel")
    assert app.try_acquire_session("a", "relabel")
    assert not app.try_acquire_session("a", "export")
    app.release_session("a", "export")
    assert app.is_busy("a")
    app.release_session("a", "relabel")
    assert not app.is_busy("a")
    assert app.try_acquire_session("a", "export")


@pytest.mark.parametrize(
    ("tab", "key", "expected"),
    [
        ("general", "enter", "input hotkey.binding"),
        ("audio", "enter", "Microphone"),
        ("recognition", "enter", "input asr.idle_unload_seconds"),
        ("live", "enter", "toggled live.diarize_mic"),
        ("checks", "r", "probe"),
    ],
)
def test_shell_settings_tab_keys_reach_the_active_tab(tmp_path, tab, key, expected):
    async def exercise():
        probes = []
        app = HubApp(
            IdleServices(),
            config_path=_config_path(tmp_path),
            doctor_probe=lambda _config, _path: probes.append("probe") or _report("ok"),
        )
        app.settings_screen.list_devices = lambda _key: []
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            app.settings_screen.select_tab(tab)
            await pilot.pause(0.1)
            before = len(probes)
            await pilot.press(key)
            await pilot.pause(0.1)
            if tab == "checks":
                assert len(probes) == before + 1
            elif expected.startswith("input "):
                assert isinstance(app.screen.focused, Input)
                assert app.settings_screen.editing == expected.removeprefix("input ")
            elif expected.startswith("toggled "):
                assert app.config_editor.config.live.diarize_mic is True
            else:
                assert isinstance(app.screen, ChoiceDialog)
                assert app.screen.dialog_title == expected

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("leave", "destination"),
    [
        ("key", "record"),
        ("click", "library"),
        ("show_library", "library"),
    ],
)
@pytest.mark.parametrize("choice", ["save", "discard", "stay"])
def test_shell_guard_asks_before_leaving_settings_with_unsaved_changes(
    tmp_path, leave, destination, choice
):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(IdleServices(), config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            app.config_editor.edit("asr.cpu_threads", "5")
            if leave == "key":
                await pilot.press("1")
            elif leave == "click":
                await pilot.click("#sidebar", offset=(4, 1))
            else:
                app.show_library()
            await pilot.pause()
            assert _prompt_text(app) == "Save or discard unsaved configuration changes?"
            await pilot.click(f"#choice-{choice}")
            await pilot.pause()
            saved = Config.load(path).asr.cpu_threads
            if choice == "stay":
                assert app.current_mode == "settings"
                assert app.config_editor.dirty
                assert saved == Config.defaults().asr.cpu_threads
            else:
                assert app.current_mode == destination
                assert not app.config_editor.dirty
                expected = 5 if choice == "save" else Config.defaults().asr.cpu_threads
                assert saved == expected
                assert app.config_editor.config.asr.cpu_threads == expected

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("key", "label", "destination", "expected"),
    [
        ("s", "[s] Save", "record", 5),
        ("d", "[d] Discard", "record", None),
        ("escape", "[esc] Stay", "settings", None),
    ],
)
def test_shell_guard_buttons_print_their_keys_and_the_keys_choose(
    tmp_path, key, label, destination, expected
):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(IdleServices(), config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            app.config_editor.edit("asr.cpu_threads", "5")
            await pilot.press("1")
            await pilot.pause()
            assert label in _screen_rows_text(app)
            await pilot.press(key)
            await pilot.pause()
            assert app.current_mode == destination
            default = Config.defaults().asr.cpu_threads
            assert Config.load(path).asr.cpu_threads == (expected or default)
            assert app.config_editor.dirty is (destination == "settings")

    asyncio.run(exercise())


def _screen_rows_text(app: HubApp) -> str:
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


def test_shell_guard_runs_on_quit_from_settings(tmp_path):
    async def exercise():
        path = _config_path(tmp_path)
        app = HubApp(IdleServices(), config_editor=ConfigEditor(path))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            app.config_editor.edit("asr.cpu_threads", "5")
            await pilot.press("q")
            await pilot.pause()
            assert _prompt_text(app) == "Save or discard unsaved configuration changes?"
            await pilot.click("#choice-stay")
            await pilot.pause()
            assert app.is_running
            assert app.current_mode == "settings"

    asyncio.run(exercise())


@pytest.mark.parametrize("screen", ["record", "library", "settings"])
def test_shell_quit_asks_while_recording_from_each_screen(screen):
    async def exercise():
        services = RecordingServices()
        app = HubApp(services)
        async with app.run_test(size=(150, 45)) as pilot:
            app.show_screen(screen)
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert prompt == "Stop recording and save before quitting?"
            await pilot.press("n")
            assert app.is_running
            assert app.current_mode == screen

    asyncio.run(exercise())


def _screen_rows(app: HubApp) -> list[str]:
    """Return the plain text of each composited row: no colour, no style."""
    return [strip.text for strip in app.screen._compositor.render_strips()]


def _tab_bar_rows(app: HubApp) -> list[str]:
    region = app.screen.query_one("#settings-tabs").region
    rows = _screen_rows(app)[region.y : region.bottom]
    return [row[region.x : region.right] for row in rows]


@pytest.mark.parametrize("tab", ["general", "recognition", "checks"])
def test_shell_settings_tab_bar_marks_the_active_tab_in_plain_text(tab):
    labels = {"general": "General", "audio": "Audio", "recognition": "Recognition"}
    labels |= {"live": "Live", "checks": "Checks"}

    async def exercise():
        app = HubApp(IdleServices(), doctor_probe=lambda _config, _path: _report("ok"))
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("3")
            app.settings_screen.select_tab(tab)
            await pilot.pause()
            text = "\n".join(_tab_bar_rows(app))
            assert text.count("▶") == 1, text
            assert f"▶ {labels[tab]}" in text, text
            widths = [app.screen.query_one(f"#tab-{name}").outer_size.width for name in labels]
            app.settings_screen.select_tab("live" if tab != "live" else "audio")
            await pilot.pause()
            moved = [app.screen.query_one(f"#tab-{name}").outer_size.width for name in labels]
            assert moved == widths, "a tab change does not move the other tabs"

    asyncio.run(exercise())
