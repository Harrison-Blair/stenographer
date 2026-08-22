# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for the PTT hotkey listener (spec §6.3).

Real, non-mocked input path: a genuine evdev.UInput keyboard advertising
KEY_A..KEY_Z plus the binding key, a HotkeyListener pointed at that device's
read-back node, and the binding key emitted down then up. Nothing is mocked —
the kernel virtual input device is the actual resource the listener reads, and
the callbacks are driven by real EV_KEY events round-tripping through it.

Self-skips unless STENOGRAPHER_INTEGRATION=1, /dev/uinput is writable, and the
created node is readable back, so the default unit run never creates an input
device.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

import evdev  # noqa: E402

from stenographer.hotkey import HotkeyListener, parse_binding  # noqa: E402

_BINDING = evdev.ecodes.KEY_RIGHTALT


def _open_uinput() -> evdev.UInput:
    keys = [*range(evdev.ecodes.KEY_A, evdev.ecodes.KEY_Z + 1), _BINDING]
    try:
        return evdev.UInput(events={evdev.ecodes.EV_KEY: keys}, name="stenographer-hotkey-smoke")
    except (PermissionError, FileNotFoundError) as exc:
        pytest.skip(f"/dev/uinput not usable: {exc}")


def test_uinput_loopback_drives_start_then_stop():
    ui = _open_uinput()
    node = ui.device.path
    try:
        probe = evdev.InputDevice(node)
        probe.close()
    except OSError as exc:
        ui.close()
        pytest.skip(f"uinput node {node} not readable: {exc}")

    starts: list[int] = []
    stops: list[int] = []
    listener = HotkeyListener(
        chord=parse_binding("KEY_RIGHTALT"),
        device_path=node,
        on_start=lambda: starts.append(1),
        on_stop=lambda: stops.append(1),
        lock=threading.RLock(),
    )
    listener.start()
    try:
        time.sleep(0.5)  # let the reader attach to the node
        ui.write(evdev.ecodes.EV_KEY, _BINDING, 1)
        ui.syn()
        time.sleep(0.2)
        ui.write(evdev.ecodes.EV_KEY, _BINDING, 0)
        ui.syn()
        time.sleep(0.2)
    finally:
        listener.stop()
        ui.close()

    assert starts == [1], "rising edge must fire on_start exactly once"
    assert stops == [1], "falling edge must fire on_stop exactly once"


def test_destroying_held_uinput_drives_one_stop_and_releases_guard():
    """A disappearing HID must contribute a final falling edge.

    Regression guard: there is deliberately no key-up. Closing the real uinput
    device destroys its read-back node while the binding remains held.
    """
    ui = _open_uinput()
    node = ui.device.path
    try:
        probe = evdev.InputDevice(node)
        probe.close()
    except OSError as exc:
        ui.close()
        pytest.skip(f"uinput node {node} not readable: {exc}")

    starts: list[int] = []
    stops: list[int] = []
    started = threading.Event()
    stopped = threading.Event()

    def on_start() -> None:
        starts.append(1)
        started.set()

    def on_stop() -> None:
        stops.append(1)
        stopped.set()

    listener = HotkeyListener(
        chord=parse_binding("KEY_RIGHTALT"),
        device_path=node,
        on_start=on_start,
        on_stop=on_stop,
        lock=threading.RLock(),
    )
    listener.start()
    try:
        time.sleep(0.5)  # let the reader attach to the node
        ui.write(evdev.ecodes.EV_KEY, _BINDING, 1)
        ui.syn()
        assert started.wait(1.0), "held binding did not drive its rising edge"

        ui.close()
        assert stopped.wait(1.0), "device loss did not promptly drive its falling edge"
        guard_started = time.monotonic()
        assert listener.wait_binding_released(timeout=0.25)
        assert time.monotonic() - guard_started < 0.25
        time.sleep(0.2)
    finally:
        listener.stop()
        ui.close()

    assert starts == [1], "held binding must fire on_start exactly once"
    assert stops == [1], "device loss must fire on_stop exactly once"
