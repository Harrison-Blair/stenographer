# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for the hub shell and its lifecycle prompts."""

from __future__ import annotations

import asyncio
import threading

import pytest
from textual.screen import Screen
from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.doctor_view import DoctorCheck, DoctorReport


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


def test_pilot_navigation_focus_and_recording_lifecycle():
    async def exercise():
        services = FakeServices()
        doctor_report = DoctorReport(
            (DoctorCheck("test", "test", "input and audio", "ok", "available", ""),), ()
        )
        app = HubApp(services, doctor_probe=lambda _config, _path: doctor_report)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.current_section == "live"
            assert "Press space to start recording" in "\n".join(
                "".join(segment.text for segment in strip._segments)
                for strip in app.screen._compositor.render_strips()
            )
            assert services.actions == []

            for key, section in zip(
                "23456", ("files", "sessions", "config", "setup", "doctor"), strict=True
            ):
                await pilot.press(key)
                assert app.current_section == section
                if section == "doctor":
                    await pilot.pause()

            doctor_row = str(app.query_one("#sidebar", Static).render()).splitlines()[-1]
            assert "Doctor" in doctor_row and doctor_row.endswith("0W 0F")

            search = Input(id="test-input")
            await app.mount(search)
            search.focus()
            await pilot.press("2")
            assert search.value == "2"
            assert app.current_section == "doctor"

            search.blur()
            await pilot.press("1")
            await pilot.press("space")
            assert services.actions == ["start-recording"]
            assert services.recording

            services.files_running = True
            await pilot.press("4")
            await pilot.press("3")
            assert app.current_section == "sessions"
            assert services.actions == ["start-recording"]
            assert services.recording
            assert services.files_running

    asyncio.run(exercise())


def test_pilot_quit_asks_before_saving_a_recording():
    async def exercise():
        services = FakeServices()
        services.recording = True
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            assert "recording" in str(app.screen.query_one("#quit-prompt", Static).render()).lower()
            await pilot.click("#cancel-quit")
            assert services.actions == []
            assert services.recording

            await pilot.press("q")
            await pilot.click("#confirm-quit")
            assert services.actions == ["stop-recording"]
            assert not services.recording

    asyncio.run(exercise())


def test_pilot_slow_recording_start_keeps_hub_responsive():
    async def exercise():
        services = FakeServices()
        services.start_entered = threading.Event()
        services.start_release = threading.Event()
        app = HubApp(services)
        async with app.run_test() as pilot:
            start_task = asyncio.create_task(pilot.press("space"))
            try:
                assert await asyncio.to_thread(services.start_entered.wait, 1)
                await asyncio.sleep(0.05)
                content = str(app.query_one("#section-content", Static).render())
                assert "Starting recording..." in content
                await pilot.press("2")
                assert app.current_section == "files"
            finally:
                services.start_release.set()
                await start_task

    asyncio.run(exercise())


def test_pilot_lifecycle_worker_finishes_after_hub_screen_unmount_without_failure():
    async def exercise():
        services = FakeServices()
        services.start_entered = threading.Event()
        services.start_release = threading.Event()

        app = HubApp(services)
        async with app.run_test() as pilot:
            start_task = asyncio.create_task(pilot.press("space"))
            try:
                assert await asyncio.to_thread(services.start_entered.wait, 1)
                worker = next(worker for worker in app.workers if worker.name == "start-recording")
                hub_screen = app.screen
                await app.push_screen(Screen())
                await hub_screen.remove()
                assert not app.is_mounted(hub_screen)

                services.start_release.set()
                await worker.wait()
            finally:
                services.start_release.set()
                await start_task

    asyncio.run(exercise())


def test_pilot_app_shutdown_during_lifecycle_work_does_not_fail_refresh():
    async def exercise():
        services = FakeServices()
        services.start_entered = threading.Event()
        services.start_release = threading.Event()
        app = HubApp(services)
        worker = None
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                hub_screen = app.screen
                worker = asyncio.create_task(app._start_recording())
                assert await asyncio.to_thread(services.start_entered.wait, 1)
                app.exit()
            assert not app.is_mounted(hub_screen)
        finally:
            services.start_release.set()
            if worker is not None:
                await worker
        assert services.recording

    asyncio.run(exercise())


def test_pilot_slow_recording_save_keeps_hub_responsive():
    async def exercise():
        services = FakeServices()
        services.recording = True
        services.stop_entered = threading.Event()
        services.stop_release = threading.Event()
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("q")
            confirm_task = asyncio.create_task(pilot.click("#confirm-quit"))
            try:
                assert await asyncio.to_thread(services.stop_entered.wait, 1)
                await asyncio.sleep(0.05)
                content = str(app.query_one("#section-content", Static).render())
                assert "Saving recording..." in content
                await pilot.press("3")
                assert app.current_section == "sessions"
            finally:
                services.stop_release.set()
                await confirm_task

    asyncio.run(exercise())


def test_pilot_slow_files_cancel_keeps_hub_responsive():
    async def exercise():
        services = FakeServices()
        services.files_running = True
        services.cancel_entered = threading.Event()
        services.cancel_release = threading.Event()
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("q")
            cancel_task = asyncio.create_task(pilot.click("#confirm-quit"))
            try:
                assert await asyncio.to_thread(services.cancel_entered.wait, 1)
                await asyncio.sleep(0.05)
                content = str(app.query_one("#section-content", Static).render())
                assert "Canceling Files job..." in content
                await pilot.press("4")
                assert app.current_section == "config"
            finally:
                services.cancel_release.set()
                await cancel_task

    asyncio.run(exercise())


@pytest.mark.parametrize("confirm_key", ["ctrl+c", "q"])
def test_pilot_quit_keys_confirm_recording_prompt(confirm_key):
    async def exercise():
        services = FakeServices()
        services.recording = True
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press(confirm_key)
            assert "recording" in str(app.screen.query_one("#quit-prompt", Static).render())
            await pilot.press(confirm_key)
            await pilot.pause(0.1)
            assert services.actions == ["stop-recording"]

    asyncio.run(exercise())


def test_pilot_quit_asks_before_cancelling_a_files_job():
    async def exercise():
        services = FakeServices()
        services.files_running = True
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.press("q")
            assert "files" in str(app.screen.query_one("#quit-prompt", Static).render()).lower()
            await pilot.click("#cancel-quit")
            assert services.actions == []
            assert services.files_running

            await pilot.press("q")
            await pilot.click("#confirm-quit")
            assert services.actions == ["cancel-files"]
            assert not services.files_running

    asyncio.run(exercise())
