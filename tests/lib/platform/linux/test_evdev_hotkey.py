# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux hotkey backend: the evdev key table, main-keyboard detection, the
acquisition back-off, and the listener's own threading and edge dispatch.

No devices are opened. The reader-loop tests drive real listener threads over a
duck-typed device (a real generator of events and a real ``close()``), which is
how the listener already treats an ``evdev.InputDevice``; opening
``/dev/input/event*`` belongs to the uinput loopback smoke in
tests/lib/hotkey/test_hotkey_smoke.py.
"""

from __future__ import annotations

import logging
import threading
import time

import evdev
import pytest

from stenographer.lib.hotkey.binding import parse_binding
from stenographer.lib.platform.linux import hotkey as hotkey_module
from stenographer.lib.platform.linux.evdev_hotkey_listener import EvdevHotkeyListener
from stenographer.lib.platform.linux.evdev_key_table import EvdevKeyTable
from stenographer.lib.platform.linux.hotkey import (
    _glob_event_nodes,
    _list_device_nodes,
    auto_detect_paths,
    is_main_keyboard,
    list_hotkey_devices,
)

_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z
_CHORD_KEY = evdev.ecodes.KEY_RIGHTALT
_HOTKEY_LOGGER = "stenographer.lib.platform.linux.hotkey"


class FakeEvent:
    """One evdev-shaped input event (``type``/``code``/``value`` is all the
    listener ever reads off one)."""

    def __init__(self, type: int, code: int, value: int) -> None:
        self.type = type
        self.code = code
        self.value = value


class FakeDevice:
    """A stand-in for an opened ``evdev.InputDevice``: a real event generator
    and a real ``close()``, so the listener's threading, edge dispatch, and
    teardown all run unchanged with nothing under /dev/input."""

    def __init__(self, path: str, events=(), error: OSError | None = None) -> None:
        self.path = path
        self.name = "fake keyboard"
        self.closed = False
        self._events = list(events)
        self._error = error

    def read_loop(self):
        yield from self._events
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self.closed = True


def _listener(device_path=None, *, chord=_CHORD_KEY):
    """A listener whose edges are recorded, wired to no device at all."""
    edges: list[str] = []
    listener = EvdevHotkeyListener(
        chord=frozenset({chord}),
        device_path=device_path,
        on_start=lambda: edges.append("start"),
        on_stop=lambda: edges.append("stop"),
        lock=threading.RLock(),
    )
    return listener, edges


def _register(listener, *devices):
    listener._devices = list(devices)
    listener._held_by_device = {id(device): set() for device in devices}


def test_key_table_round_trips_canonical_names():
    keys = EvdevKeyTable()
    assert keys.code("KEY_RIGHTCTRL") == evdev.ecodes.KEY_RIGHTCTRL
    assert keys.name(evdev.ecodes.KEY_RIGHTCTRL) == "KEY_RIGHTCTRL"
    # Aliased codes resolve to the first (canonical) evdev name.
    assert keys.name(evdev.ecodes.KEY_MUTE) == "KEY_MIN_INTERESTING"
    assert keys.name(0x7FFF) is None
    with pytest.raises(KeyError):
        keys.code("KEY_NOPE")


def test_parse_binding_through_the_evdev_table():
    assert parse_binding("KEY_LEFTCTRL+KEY_A", EvdevKeyTable()) == frozenset(
        {evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_A}
    )


def test_main_keyboard_true_for_plain_named_full_keyboard():
    codes = range(_KEY_A, _KEY_Z + 1)  # >= 10 codes in the letter range
    assert is_main_keyboard("My Keyboard", codes) is True


def test_mouse_name_is_rejected_even_with_letter_keys():
    codes = range(_KEY_A, _KEY_Z + 1)
    assert is_main_keyboard("Logitech USB Mouse", codes) is False


def test_consumer_control_name_is_rejected():
    codes = range(_KEY_A, _KEY_Z + 1)
    assert is_main_keyboard("Keychron Q1 Consumer Control", codes) is False


def test_too_few_letter_keys_is_rejected():
    assert is_main_keyboard("Volume Dial", [_KEY_A, _KEY_A + 1, _KEY_A + 2]) is False


def test_unopenable_explicit_device_backs_off_instead_of_spinning():
    """An explicit hotkey.device that cannot be opened (unplugged, stale path, or
    a permissions gap) must back off between retries, not busy-loop the CPU.

    Regression guard: _resolve_paths returns the explicit path unconditionally,
    so the acquisition loop must sleep on a failed open rather than re-detecting
    instantly. A nonexistent path makes evdev.InputDevice raise a real OSError —
    no device is ever created, so this stays a control-flow test. The retry rate
    is observed by counting _resolve_paths calls; the busy-loop bug does
    thousands in 0.3s, the backoff does a handful.

    Seen to FAIL against the pre-fix listener (count in the thousands).
    """
    listener = EvdevHotkeyListener(
        chord=parse_binding("KEY_RIGHTALT", EvdevKeyTable()),
        device_path="/dev/input/stenographer-nonexistent",
        on_start=lambda: None,
        on_stop=lambda: None,
        lock=threading.RLock(),
    )
    calls = {"n": 0}
    real_resolve = listener._resolve_paths

    def counting_resolve():
        calls["n"] += 1
        return real_resolve()

    listener._resolve_paths = counting_resolve
    listener.start()
    try:
        time.sleep(0.3)
    finally:
        listener.stop()

    assert calls["n"] < 20, f"listener spun {calls['n']} times in 0.3s (expected backoff)"


def test_the_device_enumeration_seams_list_paths_without_opening_any():
    # Both seams only name character devices under /dev/input; opening one is
    # the caller's job, and belongs to the smoke suite.
    globbed = _glob_event_nodes()
    assert all(path.startswith("/dev/input/event") for path in globbed)
    assert globbed == sorted(globbed)
    # evdev's own enumeration filters the very same nodes by device type, so it
    # is always a subset of the glob — a real relationship even on a host with
    # no input nodes at all, where it forces both to be empty.
    assert set(_list_device_nodes()) <= set(globbed)


def test_auto_detect_skips_event_nodes_it_cannot_open(monkeypatch, caplog):
    """An unopenable node is skipped, not fatal.

    A permissions gap on one HID (or a node that vanished between the glob and
    the open) must cost that device only — detection still answers for the rest.
    """
    monkeypatch.setattr(
        hotkey_module,
        "_glob_event_nodes",
        lambda: ["/dev/input/stenographer-nonexistent0", "/dev/input/stenographer-nonexistent1"],
    )
    with caplog.at_level(logging.DEBUG, logger=_HOTKEY_LOGGER):
        assert auto_detect_paths() == []
    skipped = {
        r.message.split("path=")[1].split(" ")[0]
        for r in caplog.records
        if "device_skipped" in r.message
    }
    assert skipped == {
        "/dev/input/stenographer-nonexistent0",
        "/dev/input/stenographer-nonexistent1",
    }


def test_start_is_idempotent_and_the_listener_restarts_after_stop():
    """A second start() must not raise a second supervisor thread.

    The configured device does not exist, so the acquisition loop only ever
    backs off — nothing is opened — while start/stop/is_running are exercised.
    """
    listener, _ = _listener("/dev/input/stenographer-nonexistent")
    listener.start()
    try:
        supervisor = listener._supervisor
        listener.start()
        assert listener._supervisor is supervisor
        assert listener.is_running is True
    finally:
        listener.stop()
    assert listener.is_running is False
    assert listener._supervisor is None
    assert listener._readers == []

    listener.start()
    try:
        assert listener.is_running is True
    finally:
        listener.stop()


def test_reacquire_returns_immediately_and_gives_up_once_stop_is_requested():
    listener, _ = _listener("/dev/input/event9")
    assert listener._reacquire() == ["/dev/input/event9"]
    listener._stop_event.set()
    # A stop during the back-off must end the acquisition loop, not outlast it.
    assert listener._reacquire() == []


def test_reader_loop_reports_both_edges_and_ignores_non_key_events():
    listener, edges = _listener()
    device = FakeDevice(
        "/dev/fake0",
        [
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 1),
            FakeEvent(evdev.ecodes.EV_SYN, 0, 0),
            # Autorepeat, all the way through the listener: a held hotkey
            # repeats for as long as it is down, and each repeat re-firing
            # on_start would restart the recording mid-utterance.
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 2),
            FakeEvent(evdev.ecodes.EV_REL, 0, 1),
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 0),
        ],
    )
    _register(listener, device)

    listener._reader_loop(device)

    assert edges == ["start", "stop"]
    # The loop always hands the device back, so a lost HID cannot leak an fd.
    assert device.closed is True
    assert listener._devices == []


def test_reader_loop_logs_a_lost_device_and_releases_the_chord_it_was_holding(caplog):
    """Losing the HID mid-press must end the recording, not latch it.

    The falling edge comes from the device's own removal, since no key-up will
    ever arrive from a keyboard that was unplugged while held.
    """
    listener, edges = _listener()
    device = FakeDevice(
        "/dev/fake0",
        [FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 1)],
        error=OSError(19, "No such device"),
    )
    _register(listener, device)

    with caplog.at_level(logging.WARNING, logger=_HOTKEY_LOGGER):
        listener._reader_loop(device)

    lost = [r for r in caplog.records if "device_lost" in r.message]
    assert edges == ["start", "stop"]
    assert device.closed is True
    assert lost and "device=/dev/fake0" in lost[0].message


def test_reader_loop_is_silent_about_a_device_lost_during_shutdown(caplog):
    # Closing the devices is how stop() ends the read loops, so the OSError it
    # causes is expected, not a fault to report.
    listener, edges = _listener()
    device = FakeDevice("/dev/fake0", error=OSError(19, "No such device"))
    _register(listener, device)
    listener._stop_event.set()

    with caplog.at_level(logging.DEBUG, logger=_HOTKEY_LOGGER):
        listener._reader_loop(device)

    assert edges == []
    assert device.closed is True
    assert not [r for r in caplog.records if "device_lost" in r.message]


def test_reader_loop_stops_once_its_device_is_no_longer_registered():
    # stop() clears the per-device state before the readers are joined; a
    # reader that keeps dispatching after that would fire an edge into a
    # listener that is already shutting down.
    listener, edges = _listener()
    device = FakeDevice(
        "/dev/fake0",
        [
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 1),
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 0),
        ],
    )
    listener._devices = [device]
    listener._held_by_device = {}

    listener._reader_loop(device)

    assert edges == []
    assert device.closed is True


def test_losing_one_device_keeps_the_others_and_reports_the_falling_edge():
    listener, edges = _listener()
    lost = FakeDevice("/dev/fake0")
    kept = FakeDevice("/dev/fake1")
    _register(listener, lost, kept)
    listener._held_by_device[id(lost)] = {_CHORD_KEY}
    with listener._held_lock:
        listener._rebuild_held()
    listener._active = True

    listener._device_lost(lost)

    assert edges == ["stop"]
    assert lost.closed is True
    assert kept.closed is False
    assert listener._devices == [kept]
    assert listener._held == set()


def test_spawn_reader_starts_a_named_daemon_thread_for_its_device():
    listener, _ = _listener()
    device = FakeDevice("/dev/fake0")
    _register(listener, device)

    reader = listener._spawn_reader(device)
    reader.join(timeout=10)

    assert reader.is_alive() is False
    # The thread name is how a stuck reader is identified in a stack dump.
    assert reader.name == "hotkey-reader:/dev/fake0"
    assert reader.daemon is True
    assert device.closed is True


def test_supervise_waits_for_the_last_reader_and_leaves_at_once_on_stop():
    listener, _ = _listener("/dev/input/event9")
    finished = threading.Thread(target=lambda: None)
    finished.start()
    listener._readers = [finished]

    started_at = time.monotonic()
    listener._supervise()
    assert listener._readers == []
    assert time.monotonic() - started_at < 5

    gate = threading.Event()
    lingering = threading.Thread(target=lambda: gate.wait(10), daemon=True)
    lingering.start()
    listener._readers = [lingering]
    listener._stop_event.set()
    try:
        started_at = time.monotonic()
        listener._supervise()
        # Stop is not a reason to wait for a reader that is still blocked in a
        # read; stop() joins them itself, with its own timeout.
        assert time.monotonic() - started_at < 0.5
        assert listener._readers == [lingering]
    finally:
        gate.set()
        lingering.join(timeout=10)


def test_rescan_skips_a_hotplugged_node_it_cannot_open(monkeypatch, caplog):
    monkeypatch.setattr(
        hotkey_module, "_glob_event_nodes", lambda: ["/dev/input/stenographer-nonexistent"]
    )
    listener, edges = _listener()
    known = FakeDevice("/dev/fake0")
    _register(listener, known)

    with caplog.at_level(logging.DEBUG, logger=_HOTKEY_LOGGER):
        listener._rescan()

    assert listener._devices == [known]
    assert listener._readers == []
    assert edges == []
    assert any("device_skipped" in record.message for record in caplog.records)


def test_listing_hotkey_devices_survives_an_unreadable_input_directory(monkeypatch, caplog):
    """An enumeration failure leaves setup and doctor with an empty list.

    This is the WARNING that explains an empty device chooser, so it has to be
    logged rather than swallowed.
    """

    def refuse():
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(hotkey_module, "_list_device_nodes", refuse)
    with caplog.at_level(logging.WARNING, logger=_HOTKEY_LOGGER):
        assert list_hotkey_devices() == []
    assert any("enumerate_failed" in record.message for record in caplog.records)


def test_listing_hotkey_devices_skips_the_nodes_it_cannot_open(monkeypatch, caplog):
    monkeypatch.setattr(
        hotkey_module, "_list_device_nodes", lambda: ["/dev/input/stenographer-nonexistent"]
    )
    with caplog.at_level(logging.DEBUG, logger=_HOTKEY_LOGGER):
        assert list_hotkey_devices() == []
    assert any("device_skipped" in record.message for record in caplog.records)


def test_stop_closes_every_device_and_joins_every_reader():
    """Shutdown owns the devices: it closes them, which is what ends the reads.

    A device left open would keep its reader thread blocked in read_loop() and
    the daemon would not exit.
    """
    listener, edges = _listener()
    devices = [FakeDevice("/dev/fake0"), FakeDevice("/dev/fake1")]
    _register(listener, *devices)
    listener._held_by_device[id(devices[0])] = {_CHORD_KEY}
    with listener._held_lock:
        listener._rebuild_held()
    listener._active = True
    gate = threading.Event()
    reader = threading.Thread(target=lambda: gate.wait(10), daemon=True)
    reader.start()
    listener._readers = [reader]

    gate.set()
    listener.stop(timeout=10)

    assert all(device.closed for device in devices)
    assert listener._devices == []
    assert listener._held == set()
    assert listener._readers == []
    # The edge state is forgotten, so the next press is a rising edge again.
    assert listener._active is False
    assert edges == []


def test_reacquire_backs_off_between_scans_instead_of_spinning():
    """With no readable device, reacquisition must wait on the stop event.

    Waiting on the event (rather than sleeping) is what lets a stop during the
    back-off end the listener immediately; a busy loop would burn a core for as
    long as the keyboard is unplugged.
    """
    listener, _ = _listener()
    scans = []

    def resolve_nothing():
        scans.append(time.monotonic())
        return []

    listener._resolve_paths = resolve_nothing
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(listener._reacquire()), daemon=True)
    worker.start()
    try:
        time.sleep(0.2)
        assert len(scans) < 5, f"reacquire scanned {len(scans)} times in 0.2s"
        listener._stop_event.set()
        worker.join(timeout=10)
        assert worker.is_alive() is False
        assert outcome == [[]]
    finally:
        listener._stop_event.set()
        worker.join(timeout=10)


def test_reader_loop_drops_an_event_that_arrives_after_stop_was_requested():
    listener, edges = _listener()
    device = FakeDevice(
        "/dev/fake0",
        [
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 1),
            FakeEvent(evdev.ecodes.EV_KEY, _CHORD_KEY, 0),
        ],
    )
    _register(listener, device)
    listener._stop_event.set()

    listener._reader_loop(device)

    # An edge dispatched here would start a session the daemon is tearing down.
    assert edges == []
    assert device.closed is True
