# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for the hub shell and its lifecycle prompts."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from textual.screen import Screen
from textual.widgets import Input, Static

from stenographer.cli.hub.dialogs import QuitConfirm
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport
from tests.cli.hub.support import make_app


class FakeServices:
    def __init__(self):
        self.recording = False
        self.files_running = False
        self.actions = []
        self.start_entered = None
        self.start_release = None
        self.stop_entered = None
        self.stop_release = None
        self.cancel_entered = None
        self.cancel_release = None

    def start_recording(self):
        self.actions.append("start-recording")
        if self.start_entered is not None:
            self.start_entered.set()
            self.start_release.wait()
        self.recording = True

    def stop_recording(self):
        self.actions.append("stop-recording")
        if self.stop_entered is not None:
            self.stop_entered.set()
            self.stop_release.wait()
        self.recording = False

    def cancel_files(self):
        self.actions.append("cancel-files")
        if self.cancel_entered is not None:
            self.cancel_entered.set()
            self.cancel_release.wait()
        self.files_running = False


async def test_pilot_shell_navigation_focus_and_recording_lifecycle(tmp_path):
    services = FakeServices()
    doctor_report = DoctorReport((DoctorCheck("test", "test", "input", "ok", "available", ""),), ())
    app = make_app(tmp_path, services, doctor_probe=lambda _config: doctor_report)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.current_mode == "record"
        assert "○ READY" in "\n".join(
            "".join(segment.text for segment in strip._segments)
            for strip in app.screen._compositor.render_strips()
        )
        assert services.actions == []

        for key, screen in zip("23", ("library", "settings"), strict=True):
            await pilot.press(key)
            assert app.current_mode == screen
        for key in "456":
            await pilot.press(key)
            assert app.current_mode == "settings"
        await pilot.pause()

        settings_row = str(app.screen.query_one("#nav-settings").label)
        assert settings_row.split() == ["▶", "3", "Settings"]

        search = Input(id="test-input")
        await app.screen.mount(search)
        search.focus()
        await pilot.press("2")
        assert search.value == "2"
        assert app.current_mode == "settings"

        search.blur()
        await pilot.press("1")
        await pilot.press("space")
        assert services.actions == ["start-recording"]
        assert services.recording

        services.files_running = True
        await pilot.press("3")
        await pilot.press("2")
        assert app.current_mode == "library"
        assert services.actions == ["start-recording"]
        assert services.recording
        assert services.files_running


async def test_pilot_quit_asks_before_saving_a_recording(tmp_path):
    services = FakeServices()
    services.recording = True
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        prompt = str(app.screen.query_one("#quit-prompt", Static).render())
        assert prompt == "Quit and do this first?\n· Stop and save the recording."
        assert str(app.screen.query_one("#cancel-quit").label) == "▶ [n] Keep recording"
        assert str(app.screen.query_one("#confirm-quit").label) == "  [y] Save and quit"
        await pilot.click("#cancel-quit")
        assert services.actions == []
        assert services.recording

        await pilot.press("q")
        await pilot.click("#confirm-quit")
        assert services.actions == ["stop-recording"]
        assert not services.recording


@pytest.mark.parametrize(
    ("initial_state", "event_prefix", "expected_text", "screen_key", "expected_mode"),
    [
        (None, "start", "Starting recording...", "2", "library"),
        ("recording", "stop", "Saving recording...", "2", "library"),
        ("files_running", "cancel", "Canceling the file job...", "3", "settings"),
    ],
)
async def test_pilot_slow_work_keeps_hub_responsive(
    initial_state, event_prefix, expected_text, screen_key, expected_mode, tmp_path
):
    services = FakeServices()
    if initial_state is not None:
        setattr(services, initial_state, True)
    entered, release = threading.Event(), threading.Event()
    setattr(services, f"{event_prefix}_entered", entered)
    setattr(services, f"{event_prefix}_release", release)
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        if initial_state is None:
            task = asyncio.create_task(pilot.press("space"))
        else:
            await pilot.press("q")
            task = asyncio.create_task(pilot.click("#confirm-quit"))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            await asyncio.sleep(0.05)
            content = str(app.record_screen.query_one("#section-content", Static).render())
            assert expected_text in content
            await pilot.press(screen_key)
            assert app.current_mode == expected_mode
        finally:
            release.set()
            await task


async def test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure(
    tmp_path, monkeypatch
):
    services = FakeServices()
    services.start_entered = threading.Event()
    services.start_release = threading.Event()

    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        start_task = asyncio.create_task(pilot.press("space"))
        try:
            assert await asyncio.to_thread(services.start_entered.wait, 1)
            worker = next(worker for worker in app.workers if worker.name == "start-recording")
            hub_screen = app.screen
            await app.push_screen(Screen())
            # The real hub removes its screens only after it stops running. A timer
            # redraw in the middle of this removal sees a screen that is still
            # attached but has no children, so no redraw runs until it ends.
            with monkeypatch.context() as patch:
                patch.setattr(app, "refresh_view", lambda: None)
                await hub_screen.remove()
            assert not app.is_mounted(hub_screen)

            services.start_release.set()
            await worker.wait()
        finally:
            services.start_release.set()
            await start_task


async def test_pilot_app_shutdown_during_lifecycle_work_does_not_fail_refresh(tmp_path):
    services = FakeServices()
    services.start_entered = threading.Event()
    services.start_release = threading.Event()
    app = make_app(tmp_path, services)
    worker = None
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            hub_screen = app.screen
            worker = asyncio.create_task(app.record_screen.start_recording())
            assert await asyncio.to_thread(services.start_entered.wait, 1)
            app.exit()
        assert not app.is_mounted(hub_screen)
    finally:
        services.start_release.set()
        if worker is not None:
            await worker
    assert services.recording


@pytest.mark.parametrize("confirm_key", ["ctrl+c", "q"])
async def test_pilot_quit_keys_confirm_recording_prompt(confirm_key, tmp_path):
    services = FakeServices()
    services.recording = True
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press(confirm_key)
        assert "recording" in str(app.screen.query_one("#quit-prompt", Static).render())
        await pilot.press(confirm_key)
        await pilot.pause(0.1)
        assert services.actions == ["stop-recording"]


class WorkServices(FakeServices):
    """Hold a recording, a stop that still saves, and a file job at the same time."""

    def __init__(self):
        super().__init__()
        self.recording = True
        self.files_running = True
        self.stopping = (SimpleNamespace(labelling_speakers=True),)
        self.stop_error = None

    @property
    def stopping_sessions(self):
        return self.stopping

    def wait_for_stops(self):
        self.actions.append("wait-for-stops")
        self.stopping = ()

    def stop_recording(self):
        if self.stop_error is not None:
            self.actions.append("stop-recording-failed")
            raise self.stop_error
        super().stop_recording()


async def test_pilot_quit_asks_once_for_all_active_work_and_runs_it_in_order(tmp_path):
    services = WorkServices()
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        prompt = str(app.screen.query_one("#quit-prompt", Static).render())
        assert prompt == (
            "Quit and do this first?\n"
            "· Stop and save the recording.\n"
            "· Finish saving the stopped recordings.\n"
            "· Cancel the running file job."
        )
        await pilot.press("n")
        await pilot.pause()
        assert services.actions == []
        assert app.is_running

        await pilot.press("q")
        await pilot.pause()
        await pilot.press("y")
        for _ in range(100):
            if not app.is_running:
                break
            assert not isinstance(app.screen, QuitConfirm), "the hub asked a second time"
            await pilot.pause(0.02)
        assert not app.is_running
    assert services.actions == [
        "stop-recording",
        "wait-for-stops",
        "cancel-files",
    ]


async def test_pilot_quit_keeps_the_hub_open_when_the_recording_cannot_save(tmp_path):
    services = WorkServices()
    services.stop_error = OSError("no space left on device")
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("y")
        for _ in range(100):
            if "stop-recording-failed" in services.actions and app.activity_status is None:
                break
            await pilot.pause(0.02)
        await pilot.pause()
        assert app.is_running
        assert app.activity_status is None
        assert services.files_running, "a failed save must not cancel the file job"
        assert "cancel-files" not in services.actions
        assert "wait-for-stops" not in services.actions
        notices = [str(notice.message) for notice in app._notifications]
        assert "Could not save the recording: no space left on device" in notices


async def test_pilot_quit_asks_before_cancelling_a_files_job(tmp_path):
    services = FakeServices()
    services.files_running = True
    app = make_app(tmp_path, services)
    async with app.run_test() as pilot:
        await pilot.press("q")
        prompt = str(app.screen.query_one("#quit-prompt", Static).render())
        assert prompt == "Quit and do this first?\n· Cancel the running file job."
        await pilot.click("#cancel-quit")
        assert services.actions == []
        assert services.files_running

        await pilot.press("q")
        await pilot.click("#confirm-quit")
        assert services.actions == ["cancel-files"]
        assert not services.files_running
