# SPDX-License-Identifier: GPL-3.0-or-later
"""LinuxPlatform wiring: every accessor really builds its own backend.

The provider's job is to hand the core the right object, lazily. Nothing here
opens an input device, fires a notification, plays a cue, takes the real
runtime lock, or touches systemd: player and notifier lookups run against a tmp
PATH, and ``restart_service()`` / ``hotkey_devices()`` are left to the smoke
suite because they would drive systemd and /dev/input respectively.
"""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path

import pytest

from stenographer.lib.hotkey.errors import BindingCaptureError
from stenographer.lib.platform.host_guidance import HostGuidance
from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.platform.linux.clipboard import copy_both_selections, copy_both_selections_x11
from stenographer.lib.platform.linux.evdev_hotkey_listener import EvdevHotkeyListener
from stenographer.lib.platform.linux.evdev_key_table import EvdevKeyTable
from stenographer.lib.platform.linux.flock_single_instance_lock import FlockSingleInstanceLock
from stenographer.lib.platform.linux.linux_cue_player import LinuxCuePlayer
from stenographer.lib.platform.linux.notify_send_notifier import NotifySendNotifier
from stenographer.lib.platform.linux.provider import LinuxPlatform
from stenographer.lib.platform.linux.uinput_keyboard import UinputKeyboard
from stenographer.lib.platform.multiprocessing_asr_transport import MultiprocessingAsrTransport


def test_provider_resolves_xdg_user_directories():
    plat = LinuxPlatform()
    home = Path("/home/alice")
    assert plat.config_path({}, home) == home / ".config/stenographer/config.toml"
    assert plat.config_path({"XDG_CONFIG_HOME": "/xdg"}, home) == Path(
        "/xdg/stenographer/config.toml"
    )
    assert plat.state_dir({}, home) == home / ".local/state/stenographer"
    assert plat.state_dir({"XDG_STATE_HOME": "/xdg"}, home) == Path("/xdg/stenographer")
    assert plat.runtime_dir({"XDG_RUNTIME_DIR": "/run/user/42"}) == Path("/run/user/42")
    # No XDG_RUNTIME_DIR: the socket/lock directory still has to be this user's.
    assert plat.runtime_dir({}) == Path(f"/run/user/{os.getuid()}")


def test_provider_speaks_the_evdev_key_vocabulary():
    keys = LinuxPlatform().keys()
    assert isinstance(keys, EvdevKeyTable)
    assert keys.name(keys.code("KEY_RIGHTCTRL")) == "KEY_RIGHTCTRL"


def test_provider_builds_an_evdev_listener_without_touching_a_device():
    listener = LinuxPlatform().hotkey_listener(
        chord=frozenset({97}),
        device="/dev/input/event9",
        on_start=lambda: None,
        on_stop=lambda: None,
        lock=threading.RLock(),
        cancel=frozenset({1}),
    )
    assert isinstance(listener, EvdevHotkeyListener)
    # Construction is inert: the device is opened by start(), not here.
    assert listener.is_running is False
    assert listener._resolve_paths() == ["/dev/input/event9"]


def test_provider_reports_an_unopenable_capture_device_in_setup_vocabulary():
    # An explicit path that does not exist never reaches a real device, and the
    # failure has to arrive as the setup flow's own error, not as OSError.
    with pytest.raises(BindingCaptureError, match="could not open hotkey device"):
        LinuxPlatform().capture_binding(
            io.StringIO(), "/dev/input/stenographer-nonexistent", timeout=0.1
        )


def test_provider_builds_the_output_backends():
    plat = LinuxPlatform()
    injector = plat.key_injector()
    assert isinstance(injector, UinputKeyboard)
    # Lazy by contract: /dev/uinput is opened on the first chord, not here.
    injector.close()
    assert plat.clipboard_writer("wl-copy") is copy_both_selections
    assert plat.clipboard_writer("x11") is copy_both_selections_x11
    # An unknown backend name in config must be refused, never silently
    # mapped onto a copier that cannot work here.
    with pytest.raises(ValueError, match="ClipboardBackend"):
        plat.clipboard_writer("telepathy")


def test_provider_builds_a_notifier_and_a_cue_player_from_what_is_installed(tmp_path, monkeypatch):
    plat = LinuxPlatform()
    monkeypatch.setenv("PATH", str(tmp_path))
    # Nothing installed: the notifier degrades to a no-op and there is no cue
    # player at all, so the daemon plays no cues rather than failing to.
    assert NotifySendNotifier.probe() is False
    assert isinstance(plat.notifier(), NotifySendNotifier)
    assert plat.cue_player() is None

    player_path = tmp_path / "pw-play"
    player_path.write_text("#!/bin/sh\nexit 0\n")
    player_path.chmod(0o755)
    player = plat.cue_player()
    assert isinstance(player, LinuxCuePlayer)
    assert player._player == "pw-play"


def test_provider_builds_process_and_lifecycle_services():
    plat = LinuxPlatform()
    assert isinstance(plat.asr_transport(), MultiprocessingAsrTransport)
    lock = plat.single_instance_lock()
    assert isinstance(lock, FlockSingleInstanceLock)
    # Not acquired here: this is the daemon's real runtime lock path, and a
    # unit test must never contend with a running daemon for it.
    assert lock._path.name == "stenographer.lock"


def test_provider_answers_the_host_probes_for_real():
    plat = LinuxPlatform()
    cores = plat.physical_core_count()
    assert cores is None or cores >= 1
    assert plat.journal_attached({"JOURNAL_STREAM": "8:123456"}) is True
    assert plat.journal_attached({}) is False
    # One live sample, shape-checked only: the fields are live host state, and
    # test_probe.py owns the field-by-field composition.
    probe = plat.probe_host()
    assert isinstance(probe, HostProbe)
    assert isinstance(probe.clipboard_backend, str)

    guidance = plat.guidance()
    assert isinstance(guidance, HostGuidance)
    assert guidance.service_name == "stenographer.service"
    assert guidance.run_with_config("/home/alice/my config.toml") == (
        "STENOGRAPHER_CONFIG='/home/alice/my config.toml' stenographer run"
    )
