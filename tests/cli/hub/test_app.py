# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless tests for the hub shell and its lifecycle prompts."""

from __future__ import annotations

import asyncio

from textual.widgets import Input, Static

from stenographer.cli.hub.app import HubApp


class FakeServices:
    def __init__(self):
        self.recording = False
        self.files_running = False
        self.actions = []

    def start_recording(self):
        self.actions.append("start-recording")
        self.recording = True

    def stop_recording(self):
        self.actions.append("stop-recording")
        self.recording = False

    def cancel_files(self):
        self.actions.append("cancel-files")
        self.files_running = False


def test_pilot_navigation_focus_and_recording_lifecycle():
    async def exercise():
        services = FakeServices()
        app = HubApp(services)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.current_section == "live"
            assert "Press space to start recording" in str(
                app.query_one("#section-content", Static).render()
            )
            assert services.actions == []

            for key, section in zip(
                "23456", ("files", "sessions", "config", "setup", "doctor"), strict=True
            ):
                await pilot.press(key)
                assert app.current_section == section

            doctor_row = str(app.query_one("#sidebar", Static).render()).splitlines()[-1]
            assert "Doctor" in doctor_row and doctor_row.endswith("0")

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
