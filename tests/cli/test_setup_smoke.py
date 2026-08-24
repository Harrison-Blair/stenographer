# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in real microphone and active-service checks for interactive setup.

These checks are intentionally observational unless their narrower opt-ins are
also set. They never download a model, install a unit, enable one, or start an
inactive unit.
"""

from __future__ import annotations

import io
import os
import pty
import select
import termios
import threading
import time

import evdev
import pytest

from stenographer.capabilities import missing_required, probe
from stenographer.cli import setup
from stenographer.cli.binding_capture import capture_binding
from stenographer.cli.calibration import calibrate_spectrum_profile
from stenographer.cli.console import Console, restart_service
from stenographer.config import Config
from stenographer.platform.linux.probe import service_status
from stenographer.status import SPECTRUM_BANDS
from stenographer.transcribe import model

pytestmark = pytest.mark.integration


def _open_binding_uinput() -> evdev.UInput:
    keys = [evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A]
    try:
        return evdev.UInput(
            events={evdev.ecodes.EV_KEY: keys},
            name="stenographer-setup-binding-smoke",
        )
    except (PermissionError, FileNotFoundError) as exc:
        pytest.skip(f"/dev/uinput not usable: {exc}")


def test_live_binding_capture_uses_real_uinput_and_restores_pty():
    ui = _open_binding_uinput()
    node = ui.device.path
    try:
        probe = evdev.InputDevice(node)
        probe.close()
    except OSError as exc:
        ui.close()
        pytest.skip(f"uinput node {node} not readable: {exc}")

    master_fd, slave_fd = pty.openpty()
    stdin = os.fdopen(os.dup(slave_fd), "r", encoding="utf-8")
    before = termios.tcgetattr(stdin.fileno())
    after = None
    result: list[str] = []
    errors: list[BaseException] = []

    def run_capture() -> None:
        try:
            result.append(capture_binding(stdin, node, timeout=3.0))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_capture)
    thread.start()
    try:
        deadline = time.monotonic() + 1.0
        while termios.tcgetattr(stdin.fileno())[3] & termios.ECHO:
            if time.monotonic() >= deadline:
                pytest.fail("binding capture did not enter quiet terminal mode")
            time.sleep(0.01)
        during = termios.tcgetattr(stdin.fileno())
        assert during[3] & termios.ISIG
        assert not during[3] & termios.ICANON

        ui.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 1)
        ui.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1)
        ui.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 2)
        ui.syn()
        ui.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0)
        ui.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_LEFTCTRL, 0)
        ui.syn()
        thread.join(timeout=4.0)
        after = termios.tcgetattr(stdin.fileno())
    finally:
        ui.close()
        stdin.close()
        os.close(master_fd)
        os.close(slave_fd)

    assert not thread.is_alive()
    assert errors == []
    assert result == ["KEY_LEFTCTRL+KEY_A"]
    assert after == before


def test_real_microphone_display_floor_calibration():
    if os.environ.get("STENOGRAPHER_CALIBRATION_SMOKE") != "1":
        pytest.skip("set STENOGRAPHER_CALIBRATION_SMOKE=1 and keep the room quiet")

    profile = calibrate_spectrum_profile(
        Config.defaults().audio.input_device,
        on_countdown=lambda _: None,
        on_voice_prompt=lambda: print("Speak normally for three seconds."),
    )

    assert len(profile) == SPECTRUM_BANDS
    assert all(-96.0 <= floor <= -13.0 for floor in profile)


def test_real_quick_setup_persists_and_runs_guided_checks(tmp_path, monkeypatch):
    if os.environ.get("STENOGRAPHER_QUICK_SETUP_SMOKE") != "1":
        pytest.skip("set STENOGRAPHER_QUICK_SETUP_SMOKE=1 and keep the room quiet")
    defaults = Config.defaults()
    if not model.is_model_cached(defaults.asr.model):
        pytest.skip(f"model is not cached: {defaults.asr.model}")

    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(config_path))
    input_master, input_slave = pty.openpty()
    output_master, output_slave = pty.openpty()
    stdin = os.fdopen(os.dup(input_slave), "r", encoding="utf-8")
    stdout = os.fdopen(os.dup(output_slave), "w", encoding="utf-8", buffering=1)
    chunks: list[bytes] = []
    stop_drain = threading.Event()

    def drain_output() -> None:
        while True:
            ready, _, _ = select.select([output_master], (), (), 0.1)
            if ready:
                try:
                    chunks.append(os.read(output_master, 4096))
                except OSError:
                    return
            elif stop_drain.is_set():
                return

    drain = threading.Thread(target=drain_output)
    drain.start()
    # auto device; keep binding; hold; default mic/volume/mute/overlay/update
    # check/sound pack; automatic spectrum; accept; save
    os.write(input_master, b"\nkeep\n\n\n\n\n\n\n\n\n\n\n")
    try:
        exit_code = setup.run(quick=True, stdin=stdin, stdout=stdout, stderr=stdout)
        expected = 78 if missing_required(probe(Config.load(config_path))) else 0
    finally:
        stdout.flush()
        stop_drain.set()
        drain.join(timeout=2.0)
        stdin.close()
        stdout.close()
        for fd in (input_master, input_slave, output_master, output_slave):
            os.close(fd)

    saved = Config.load(config_path)
    output = b"".join(chunks).decode(errors="replace")
    assert exit_code == expected
    assert saved.audio.min_speech_rms == defaults.audio.min_speech_rms
    assert saved.audio.max_recording_seconds == defaults.audio.max_recording_seconds
    assert saved.asr == defaults.asr
    assert isinstance(saved.feedback.spectrum_floor_dbfs, tuple)
    assert len(saved.feedback.spectrum_floor_dbfs) == SPECTRUM_BANDS
    assert "systemd unit:" in output
    if exit_code == 0:
        assert "Try a real dictation" in output


def test_restart_policy_uses_real_user_service_status():
    _, active = service_status()

    assert setup.restart_eligible(
        config_changed=True,
        custom_config=False,
        missing_required=False,
        service_active=active,
    ) is (active == "active")


def test_real_active_service_restart():
    if os.environ.get("STENOGRAPHER_SETUP_RESTART_SMOKE") != "1":
        pytest.skip("set STENOGRAPHER_SETUP_RESTART_SMOKE=1 to restart an active user service")
    if os.environ.get("STENOGRAPHER_CONFIG"):
        pytest.skip("a custom STENOGRAPHER_CONFIG must never trigger service restart")
    caps = probe(Config.defaults())
    if caps.service_active != "active":
        pytest.skip("stenographer.service is not active; setup must not start it")
    if missing_required(caps):
        pytest.skip("setup must not restart while a required capability is missing")

    output = io.StringIO()
    console = Console(io.StringIO(), output, output)

    assert restart_service(console) is True
    assert "Restarted stenographer.service" in output.getvalue()
