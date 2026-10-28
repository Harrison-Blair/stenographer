# SPDX-License-Identifier: GPL-3.0-or-later
"""Pilot tests for the Record screen through the real hub services and a fake live session."""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import threading
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from textual.widgets import Input, Select, Static

from stenographer.cli.hub.app import HubApp
from stenographer.cli.hub.engine_sampler import EngineSampler
from stenographer.cli.hub.rename_dialog import RenameDialog
from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.widgets.button import HubButton
from stenographer.lib.config.defaults import default_toml
from stenographer.lib.config.models import Config
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.null_process_counters import NullProcessCounters
from stenographer.lib.sessions import SessionStore

MIC_BYTES = 88 * 1024 * 1024
SYSTEM_BYTES = 209_716


class FakeLiveSession:
    """Stand in for ``LiveSession``: no audio, no worker; the test drives each state."""

    def __init__(self, root: Path, number: int, **options) -> None:
        self.options = options
        self.path = root / f"20261027T13035{number}Z"
        self.path.mkdir(parents=True)
        (self.path / "session.json").write_text(
            json.dumps({"current_revision": "transcript.jsonl", "kind": "rec"}), encoding="utf-8"
        )
        self.paused = False
        self.elapsed_seconds = 728.0
        self.source_states = {
            "mic": "on" if options.get("mic", True) else "off",
            "system": "on" if options.get("system", True) else "off",
        }
        self.source_reasons = {"mic": None, "system": None}
        self.speech_detected = {"mic": False, "system": False}
        self.levels_dbfs = {"mic": -31.0, "system": -52.0}
        self.meter_floor_dbfs = -70.0
        self.failed_phrase_count = 0
        self.queue_depth = 0
        self.idle_unload_deadline = None
        self.process_ids = ()
        self.model_name = "bark-pro-int8"
        self.relabel_progress = None
        self.relabel_total = 3 * number
        self.lines = [
            TranscriptLine(1.0, 3.5, "wall", "mic", "you", "You", "alpha bravo charlie"),
            TranscriptLine(4.0, 5.0, "wall", "system", "speaker-1", "Speaker 1", "delta echo"),
        ]
        self.speakers = (("speaker-1", "Speaker 1"),)
        self.listeners = []
        self.actions = []
        self.stop_entered = threading.Event()
        self.release = threading.Event()
        self.skipped = False

    def start(self):
        self.actions.append("start")

    def add_block_listener(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def toggle(self, source):
        self.actions.append(("toggle", source))
        self.source_states[source] = "off" if self.source_states[source] == "on" else "on"

    def pause(self):
        self.actions.append("pause")
        self.paused = True

    def resume(self):
        self.actions.append("resume")
        self.paused = False

    def rename(self, speaker_id, name):
        self.actions.append(("rename", speaker_id, name))
        self.speakers = tuple(
            (current, name if current == speaker_id else label) for current, label in self.speakers
        )
        self.lines = [
            replace(line, label=name) if line.speaker_id == speaker_id else line
            for line in self.lines
        ]

    def skip_relabel(self):
        self.skipped = True

    def stop(self):
        """Save the audio and the transcript, then run a slow relabel pass."""
        self.actions.append("stop")
        with open(self.path / "mic.flac", "wb") as audio:
            audio.truncate(MIC_BYTES)
        with open(self.path / "system.flac", "wb") as audio:
            audio.truncate(SYSTEM_BYTES)
        (self.path / "transcript.jsonl").write_text(
            "".join(json.dumps(asdict(line)) + "\n" for line in self.lines), encoding="utf-8"
        )
        self.relabel_progress = (self.relabel_total // 3, self.relabel_total)
        self.stop_entered.set()
        # Bounded, so a failed assertion ends the test instead of hanging its exit.
        for _ in range(500):
            if self.release.wait(0.01) or self.skipped:
                break
        self.relabel_progress = None


class FakePlatform:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def data_dir(self, _env, _home):
        return self._data_dir

    def asr_transport(self):
        return "fake-transport"

    def process_counters(self):
        return NullProcessCounters()


def _services(tmp_path: Path, devices=()):
    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    for model in LIVE_MODELS:
        (model_dir / model.filename).touch()
    sessions_root = tmp_path / "sessions"
    created: list[FakeLiveSession] = []

    def factory(_config, **options):
        session = FakeLiveSession(sessions_root, len(created) + 1, **options)
        created.append(session)
        return session

    services = HubServices(
        Config.defaults(),
        FakePlatform(tmp_path),
        session_factory=factory,
        session_store=SessionStore(sessions_root),
        device_query=lambda: list(devices),
    )
    return services, created


def _app(services, **kwargs) -> HubApp:
    sampler = EngineSampler(services, counters=NullProcessCounters(), cpu_count=1)
    return HubApp(services, engine_sampler=sampler, **kwargs)


def _screen_text(app: HubApp) -> str:
    return "\n".join(
        "".join(segment.text for segment in strip._segments)
        for strip in app.screen._compositor.render_strips()
    )


def _hints(app: HubApp) -> str:
    return app.screen.query_one("#key-hints", Static).render().plain


def _engine_state(app: HubApp) -> str:
    return str(app.screen.query_one("#engine-state", Static).render())


def _card(app: HubApp) -> str:
    return str(app.screen.query_one("#sidebar-card", Static).render())


async def _until(pilot, condition, message="condition not met") -> None:
    for _ in range(200):
        if condition():
            return
        await pilot.pause(0.02)
    raise AssertionError(message)


IDLE_HINTS = "space record · d device · m mic · s system · v view · 1 2 3 screens · ? help · q quit"
RECORDING_HINTS = (
    "enter stop & save · space pause · m mic · s system · v view · r rename · 1 2 3 screens"
    " · ? help · q quit"
)
SAVED_HINTS = (
    "space record again · o open in Library · d device · m mic · s system · v view · r rename"
    " · 1 2 3 screens · ? help · q quit"
)


def test_record_lifecycle_stops_without_quit_and_shows_the_saved_session(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            text = _screen_text(app)
            assert "[space] ● Record" in text
            assert "Default input" in text
            assert "not recording" in text
            assert _hints(app) == IDLE_HINTS

            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            app.refresh_view()
            await pilot.pause()
            session = created[0]
            text = _screen_text(app)
            assert "● REC" in text and "started " in text
            assert "[enter] ■ Stop & save" in text and "[space] Ⅱ Pause" in text
            assert _hints(app) == RECORDING_HINTS
            assert _engine_state(app) == "ready"

            await pilot.press("space")
            await _until(pilot, lambda: session.paused)
            app.refresh_view()
            await pilot.pause()
            assert "Ⅱ PAUSED" in _screen_text(app)
            assert "[space] ▶ Resume" in _screen_text(app)
            assert _hints(app) == RECORDING_HINTS.replace("space pause", "space resume")
            await pilot.press("space")
            await _until(pilot, lambda: not session.paused)

            await pilot.press("enter")
            await _until(pilot, session.stop_entered.is_set)
            await pilot.pause()
            assert app.is_running
            assert services.stopping_sessions == (session,)
            assert not services.recording
            assert app.is_busy(session.path.name)
            app.refresh_view()
            await pilot.pause()
            text = _screen_text(app)
            assert "■ SAVED" in text and "saved " in text
            assert session.path.name in text
            assert "[space] ● Record again" in text and "[o] Open in Library" in text
            assert "relabeling…" in text
            assert _engine_state(app) == "relabeling 1 of 3"
            assert "busy" in _card(app)
            assert _hints(app) == SAVED_HINTS
            # The app answers keys during the slow pass.
            await pilot.press("v")
            assert "MIC · what you said" in _screen_text(app)
            await pilot.press("v")
            await pilot.press("r")
            await pilot.pause()
            assert not isinstance(app.screen, RenameDialog)
            assert any("session busy" in notice.message for notice in app._notifications)

            session.release.set()
            await _until(pilot, lambda: services.stopping_sessions == ())
            await _until(pilot, lambda: not app.is_busy(session.path.name))
            app.refresh_view()
            await pilot.pause()
            text = _screen_text(app)
            assert "relabeling…" not in text
            assert "── saved · 2 phrases · mic.flac 88 MB · system.flac 0.2 MB ──" in text
            assert "busy" not in _card(app)
            assert not session.skipped

            await pilot.press("o")
            assert app.current_mode == "library"
            panel = app.library_screen.sessions_panel
            await _until(pilot, lambda: panel.selected_session_id == session.path.name)

            await pilot.press("1")
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            assert len(created) == 2 and services.session is created[1]

    asyncio.run(exercise())


def test_record_rename_button_is_disabled_while_the_session_is_busy(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            await pilot.press("enter")
            await _until(pilot, session.stop_entered.is_set)
            await _until(pilot, lambda: app.is_busy(session.path.name))
            app.refresh_view()
            await pilot.pause()
            button = app.screen.query_one("#card-r", HubButton)
            assert button.disabled
            assert "busy" in _card(app)

            await pilot.click("#card-r")
            await pilot.pause()
            assert not isinstance(app.screen, RenameDialog)

            session.release.set()
            await _until(pilot, lambda: not app.is_busy(session.path.name))
            await _until(pilot, lambda: not app.screen.query_one("#card-r", HubButton).disabled)
            await pilot.click("#card-r")
            await pilot.pause()
            assert isinstance(app.screen, RenameDialog)

    asyncio.run(exercise())


def test_record_saved_buttons_by_click_match_their_keys(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            await pilot.click("#rec-primary")
            await _until(pilot, lambda: services.recording)
            app.refresh_view()
            await pilot.pause()
            await pilot.click("#rec-secondary")
            await _until(pilot, lambda: created[0].paused)
            app.refresh_view()
            await pilot.pause()
            await pilot.click("#rec-primary")
            await _until(pilot, lambda: services.stopping_sessions == (created[0],))
            created[0].release.set()
            await _until(pilot, lambda: services.stopping_sessions == ())
            app.refresh_view()
            await pilot.pause()
            await pilot.click("#rec-secondary")
            await pilot.pause()
            assert app.current_mode == "library"

    asyncio.run(exercise())


def test_record_overlapping_stops_keep_the_first_on_the_engine_card(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            for _ in range(2):
                await pilot.press("space")
                await _until(pilot, lambda: services.recording)
                await pilot.press("enter")
                await _until(pilot, lambda: not services.recording)
            first, second = created
            await _until(pilot, second.stop_entered.is_set)
            assert services.stopping_sessions == (first, second)
            assert app.is_busy(first.path.name) and app.is_busy(second.path.name)

            await pilot.press("2")
            await pilot.press("1")
            app.refresh_view()
            await pilot.pause()
            assert _engine_state(app) == "relabeling 1 of 3"
            assert second.path.name in _screen_text(app)

            first.release.set()
            await _until(pilot, lambda: services.stopping_sessions == (second,))
            await _until(pilot, lambda: not app.is_busy(first.path.name))
            assert app.is_busy(second.path.name)
            app.refresh_view()
            await pilot.pause()
            assert _engine_state(app) == "relabeling 2 of 6"

            second.release.set()
            await _until(pilot, lambda: not app.is_busy(second.path.name))
            assert services.stopping_sessions == ()

    asyncio.run(exercise())


def test_record_quit_during_two_relabel_passes_skips_both(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            for _ in range(2):
                await pilot.press("space")
                await _until(pilot, lambda: services.recording)
                await pilot.press("enter")
                await _until(pilot, lambda: not services.recording)
            await _until(pilot, created[1].stop_entered.is_set)

            await pilot.press("q")
            await pilot.pause()
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert prompt == "Relabel is still running. Quit and keep the live labels?"
            await pilot.press("n")
            await pilot.pause()
            assert app.is_running
            assert not any(session.skipped for session in created)

            await pilot.press("q")
            await pilot.press("y")
            await _until(pilot, lambda: not app.is_running, "the hub did not quit")
        assert all(session.skipped for session in created)
        assert services.stopping_sessions == ()

    asyncio.run(exercise())


def test_record_quit_while_recording_asks_then_saves(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            await pilot.press("q")
            await pilot.pause()
            prompt = str(app.screen.query_one("#quit-prompt", Static).render())
            assert prompt == "Stop recording and save before quitting?"
            await pilot.press("n")
            assert services.recording
            created[0].release.set()
            await pilot.press("q")
            await pilot.press("y")
            await _until(pilot, lambda: not app.is_running, "the hub did not quit")
        assert "stop" in created[0].actions

    asyncio.run(exercise())


def test_record_meters_follow_blocks_speech_and_source_choice(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            mic = app.screen.query_one("#mic-meter")
            system = app.screen.query_one("#system-meter")
            assert mic.model.state == "idle" and system.model.state == "idle"
            assert "captures the default output mix" in _screen_text(app)

            await pilot.press("s")
            await pilot.pause()
            assert system.model.state == "off"
            assert "off · press s to enable" in _screen_text(app)
            await pilot.press("m")
            await pilot.pause()
            assert "off · press m to enable" in _screen_text(app)
            await pilot.press("m")
            await pilot.pause()
            assert mic.model.state == "idle"

            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            assert session.options["mic"] is True and session.options["system"] is False
            app.refresh_view()
            await pilot.pause()
            assert mic.model.state == "on" and system.model.state == "off"
            assert len(session.listeners) == 1
            assert mic.model.rows == (" " * 35,) * 8

            tone = 0.5 * np.sin(2 * math.pi * 440 * np.arange(1600) / 16000).astype(np.float32)
            for _ in range(5):
                session.listeners[0]("mic", tone)
            assert any("█" in row for row in mic.model.rows)
            assert "dBFS  peak" in mic.model.level_text

            assert "○ quiet" in _screen_text(app)
            session.speech_detected = {"mic": True, "system": False}
            app.refresh_view()
            await pilot.pause()
            assert "● speech" in _screen_text(app)

            await pilot.press("m")
            await _until(pilot, lambda: ("toggle", "mic") in session.actions)
            app.refresh_view()
            await pilot.pause()
            assert mic.model.state == "off"

            await pilot.press("enter")
            await _until(pilot, session.stop_entered.is_set)
            assert session.listeners == []
            session.release.set()

    asyncio.run(exercise())


def test_record_device_dialog_sets_the_next_session_device_only(tmp_path):
    async def exercise():
        config_path = tmp_path / "config.toml"
        config_path.write_text(default_toml(), encoding="utf-8")
        before = config_path.read_bytes()
        devices = (("2", "2: Alpha USB mic"), ("5", "5: Bravo headset"))
        services, created = _services(tmp_path, devices)
        app = _app(services, config_path=config_path)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("d")
            await pilot.pause()
            text = _screen_text(app)
            assert "Input device" in text
            assert "2: Alpha USB mic" in text and "5: Bravo headset" in text
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert "5: Bravo headset" in _screen_text(app)
            assert "Default input" not in _screen_text(app)

            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            assert created[0].options["device"] == "5"
            await pilot.press("d")
            await pilot.pause()
            assert app.screen is app.record_screen
            created[0].release.set()

            # A click opens the dialog too and picks the clicked choice.
            await pilot.press("enter")
            await _until(pilot, lambda: services.stopping_sessions == ())
            await pilot.click("#device-button")
            await pilot.pause()
            assert "Input device" in _screen_text(app)
            await pilot.click("#dialog-cancel")
            await pilot.pause()
            assert app.screen is app.record_screen
        assert config_path.read_bytes() == before

    asyncio.run(exercise())


def test_record_transcript_split_view_and_talk_time(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            app.refresh_view()
            await pilot.pause()
            text = _screen_text(app)
            assert "transcript · 2 speakers" in text
            mixed = [row for row in text.splitlines() if "alpha bravo" in row]
            assert len(mixed) == 1 and "00:00:01" in mixed[0] and "You" in mixed[0]
            card = _card(app)
            assert "You" in card and "0:02" in card
            assert "Speaker 1" in card and "0:01" in card
            assert "[r] Rename…" in text and "[r] Rename…" not in card

            await pilot.press("v")
            split = _screen_text(app)
            assert "MIC · what you said" in split and "SYSTEM · everyone else" in split
            rows = [row for row in split.splitlines() if "alpha" in row or "delta" in row]
            assert len(rows) == 2
            assert "alpha" in rows[0] and "delta" not in rows[0]
            assert "delta" in rows[1] and "alpha" not in rows[1]
            await pilot.click("#view-button")
            assert "MIC · what you said" not in _screen_text(app)
            created[0].release.set()

    asyncio.run(exercise())


def test_record_transcript_follows_at_bottom_and_holds_when_scrolled_up(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            session.lines = [
                TranscriptLine(float(i), float(i + 1), "wall", "mic", "you", "You", f"line {i}")
                for i in range(60)
            ]
            app.refresh_view()
            await pilot.pause()
            scroll = app.screen.query_one("#transcript")
            await _until(pilot, lambda: scroll.max_scroll_y > 0)
            assert scroll.scroll_y == scroll.max_scroll_y

            await pilot.press("home")
            await pilot.press("down")
            assert scroll.scroll_y == 1
            session.lines.append(TranscriptLine(60.0, 61.0, "wall", "mic", "you", "You", "new"))
            app.refresh_view()
            await pilot.pause()
            assert scroll.scroll_y == 1

            await pilot.press("end")
            session.lines.append(TranscriptLine(61.0, 62.0, "wall", "mic", "you", "You", "last"))
            app.refresh_view()
            await pilot.pause()
            assert scroll.scroll_y == scroll.max_scroll_y
            session.release.set()

    asyncio.run(exercise())


def test_record_rename_on_the_live_session_by_key_and_by_click(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]

            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, RenameDialog)
            assert "Rename speaker" in _screen_text(app)
            assert "[esc] Cancel" in _screen_text(app) and "[enter] Rename" in _screen_text(app)
            app.screen.query_one("#speaker-select", Select).value = "speaker-1"
            name = app.screen.query_one("#speaker-name", Input)
            name.focus()
            name.value = "Golf"
            await pilot.press("enter")
            await pilot.pause()
            assert ("rename", "speaker-1", "Golf") in session.actions

            await pilot.press("r")
            await pilot.pause()
            app.screen.query_one("#speaker-select", Select).value = "speaker-1"
            app.screen.query_one("#speaker-name", Input).value = "Hotel"
            await pilot.click("#dialog-rename")
            await pilot.pause()
            assert ("rename", "speaker-1", "Hotel") in session.actions
            assert "Hotel" in _screen_text(app)

            await pilot.press("r")
            await pilot.press("escape")
            await pilot.press("r")
            await pilot.click("#dialog-cancel")
            await pilot.pause()
            assert len([a for a in session.actions if a[0] == "rename"]) == 2
            session.release.set()

    asyncio.run(exercise())


def test_record_rename_on_the_saved_session_writes_a_revision(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            session.release.set()
            await pilot.press("enter")
            await _until(pilot, lambda: services.stopping_sessions == ())
            await _until(pilot, lambda: not app.is_busy(session.path.name))

            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, RenameDialog)
            app.screen.query_one("#speaker-select", Select).value = "you"
            app.screen.query_one("#speaker-name", Input).value = "India"
            await pilot.click("#dialog-rename")
            store = services.session_store
            await _until(
                pilot, lambda: store.read(session.path.name).revision != "transcript.jsonl"
            )
            detail = store.read(session.path.name)
            assert [line.label for line in detail.lines] == ["India", "Speaker 1"]
            await _until(pilot, lambda: "India" in _screen_text(app))
            assert not any(action[0] == "rename" for action in session.actions)

    asyncio.run(exercise())


def test_record_hub_modules_do_not_import_the_live_command():
    hub = Path(__file__).parents[3] / "src" / "stenographer" / "cli" / "hub"
    result = subprocess.run(
        ["grep", "-rn", "cli.live", str(hub)], capture_output=True, text=True, check=False
    )
    assert result.stdout == ""


def test_record_services_choose_sources_and_device_for_this_run_only(tmp_path):
    services, created = _services(tmp_path, (("3", "3: Charlie mic"),))
    assert services.input_devices() == [("3", "3: Charlie mic")]
    services.toggle_next_source("system")
    services.choose_device("3", "3: Charlie mic")
    services.start_recording()
    assert created[0].options == {
        "diarize_mic": False,
        "platform": services._platform,
        "mic": True,
        "system": False,
        "device": "3",
    }
    assert services.next_device_label == "3: Charlie mic"
    assert services.update_config(Config.defaults()) is None
    assert services.next_device == "3"
    created[0].release.set()
    stopped = services.begin_stop()
    assert stopped is created[0] and services.last_saved is stopped
    assert services.stopping_sessions == (stopped,)
    services.finish_stop(stopped)
    assert services.stopping_sessions == ()
    assert services.wait_for_stops(timeout=0.1)


def test_record_services_skip_each_pass_and_wait(tmp_path):
    services, created = _services(tmp_path)
    workers = []
    for _ in range(2):
        services.start_recording()
        session = services.begin_stop()
        worker = threading.Thread(target=services.finish_stop, args=(session,))
        worker.start()
        workers.append(worker)
    for session in created:
        assert session.stop_entered.wait(1)
    assert not services.wait_for_stops(timeout=0.05)
    services.skip_relabels()
    assert services.wait_for_stops(timeout=2)
    assert all(session.skipped for session in created)
    for worker in workers:
        worker.join(1)


def test_record_meter_head_clicks_match_their_keys(tmp_path):
    async def exercise():
        services, created = _services(tmp_path, devices=[(3, "USB mic")])
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause()
            mic = app.screen.query_one("#mic-meter")
            system = app.screen.query_one("#system-meter")
            assert mic.model.head[0].startswith("[m] MIC")
            assert system.model.head[0].startswith("[s] SYSTEM")

            # Offset (2, 1) is the first head cell inside the border and padding.
            await pilot.click("#mic-meter", offset=(2, 1))
            await pilot.pause()
            assert mic.model.state == "off" and system.model.state == "idle"
            await pilot.click("#system-meter", offset=(2, 1))
            await pilot.pause()
            assert system.model.state == "off"
            await pilot.click("#system-meter", offset=(2, 1))
            await pilot.click("#mic-meter", offset=(2, 1))
            await pilot.pause()
            assert mic.model.state == "idle" and system.model.state == "idle"

            # A click on the bars is not a control.
            await pilot.click("#mic-meter", offset=(2, 4))
            await pilot.pause()
            assert mic.model.state == "idle"

            # The right token "[d] device" ends at the last content cell.
            assert mic.model.head[1] == "[d] device"
            await pilot.click("#mic-meter", offset=(mic.size.width - 3, 1))
            await _until(pilot, lambda: "Input device" in _screen_text(app), "no device dialog")
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            await pilot.click("#mic-meter", offset=(2, 1))
            await _until(pilot, lambda: ("toggle", "mic") in session.actions)
            await pilot.click("#system-meter", offset=(2, 1))
            await _until(pilot, lambda: ("toggle", "system") in session.actions)
            session.release.set()

    asyncio.run(exercise())


def test_record_rename_button_in_the_speakers_card_opens_the_dialog(tmp_path):
    async def exercise():
        services, created = _services(tmp_path)
        app = _app(services)
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.press("space")
            await _until(pilot, lambda: services.recording)
            session = created[0]
            button = app.screen.query_one("#card-r", HubButton)
            assert str(button.label) == "[r] Rename…"
            assert "[r] Rename…" not in _card(app)

            await pilot.click("#card-r")
            await pilot.pause()
            assert isinstance(app.screen, RenameDialog)
            app.screen.query_one("#speaker-select", Select).value = "speaker-1"
            app.screen.query_one("#speaker-name", Input).value = "Juliet"
            await pilot.click("#dialog-rename")
            await pilot.pause()
            assert ("rename", "speaker-1", "Juliet") in session.actions
            session.release.set()

    asyncio.run(exercise())
