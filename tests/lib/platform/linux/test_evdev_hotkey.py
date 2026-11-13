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
from stenographer.lib.platform.linux.evdev_key_table import EvdevKeyTable
from stenographer.lib.platform.linux.hotkey import (
    EvdevHotkeyListener,
    _glob_event_nodes,
    auto_detect_paths,
    is_main_keyboard,
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


def _listener():
    """A listener whose edges are recorded, wired to no device at all."""
    edges: list[str] = []
    listener = EvdevHotkeyListener(
        lock=threading.RLock(),
        bindings={"default": frozenset({_CHORD_KEY})},
        on_binding_start=lambda _name: edges.append("start"),
        on_binding_stop=lambda _name: edges.append("stop"),
    )
    return listener, edges


def _detect(monkeypatch, *paths):
    """Make keyboard detection report exactly *paths*; returns the call times."""
    calls: list[float] = []

    def detect():
        calls.append(time.monotonic())
        return list(paths)

    monkeypatch.setattr(hotkey_module, "auto_detect_paths", detect)
    return calls


def _first_scan(monkeypatch) -> threading.Event:
    """Wrap the replaced detection; the returned event is set at its first call."""
    scanned = threading.Event()
    detect = hotkey_module.auto_detect_paths

    def signalled():
        scanned.set()
        return detect()

    monkeypatch.setattr(hotkey_module, "auto_detect_paths", signalled)
    return scanned


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


def test_detected_device_that_cannot_be_opened_backs_off_instead_of_spinning(monkeypatch):
    """A detected keyboard that cannot be opened (unplugged between detection
    and open) must back off between retries, not busy-loop the CPU.

    Regression guard: while detection keeps listing the path, _reacquire returns
    it at once, so the acquisition loop must sleep on a failed open rather than
    re-detecting instantly. A nonexistent path makes evdev.InputDevice raise a
    real OSError — no device is ever created, so this stays a control-flow test.
    The retry rate is observed by counting detection calls; the busy-loop bug
    does thousands in 0.3s, the backoff does a handful.

    Seen to FAIL against the pre-fix listener (count in the thousands).
    """
    calls = _detect(monkeypatch, "/dev/input/stenographer-nonexistent")
    scanned = _first_scan(monkeypatch)
    listener = EvdevHotkeyListener(
        lock=threading.RLock(),
        bindings={"default": parse_binding("KEY_RIGHTALT", EvdevKeyTable())},
        on_binding_start=lambda _name: None,
        on_binding_stop=lambda _name: None,
    )
    listener.start()
    try:
        # The window starts at the first scan, not at Thread.start(), so a late
        # thread start on a loaded machine cannot empty it.
        assert scanned.wait(10), "listener never scanned for keyboards"
        time.sleep(0.3)
        # Still retrying, not given up: a listener that returns at once would
        # also scan fewer than 20 times.
        assert listener.is_running, "listener exited instead of retrying"
        assert len(calls) < 20, f"listener spun {len(calls)} times in 0.3s (expected backoff)"
    finally:
        listener.stop()


def test_the_device_enumeration_seam_lists_paths_without_opening_any():
    # The seam only name character devices under /dev/input; opening one is
    # the caller's job, and belongs to the smoke suite.
    globbed = _glob_event_nodes()
    assert all(path.startswith("/dev/input/event") for path in globbed)
    assert globbed == sorted(globbed)


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


def test_start_is_idempotent_and_the_listener_restarts_after_stop(monkeypatch):
    """A second start() must not raise a second supervisor thread.

    The detected device does not exist, so the acquisition loop only ever
    backs off — nothing is opened — while start/stop/is_running are exercised.
    """
    _detect(monkeypatch, "/dev/input/stenographer-nonexistent")
    listener, _ = _listener()
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


def test_reacquire_returns_immediately_and_gives_up_once_stop_is_requested(monkeypatch):
    _detect(monkeypatch, "/dev/input/event9")
    listener, _ = _listener()
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
    listener._key_event(id(lost), _CHORD_KEY, 1)
    assert edges == ["start"]

    listener._device_lost(lost)

    assert edges == ["start", "stop"]
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
    listener, _ = _listener()
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


def test_stop_closes_every_device_and_joins_every_reader():
    """Shutdown owns the devices: it closes them, which is what ends the reads.

    A device left open would keep its reader thread blocked in read_loop() and
    the daemon would not exit.
    """
    listener, edges = _listener()
    devices = [FakeDevice("/dev/fake0"), FakeDevice("/dev/fake1")]
    _register(listener, *devices)
    listener._key_event(id(devices[0]), _CHORD_KEY, 1)
    assert edges == ["start"]
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
    assert listener._selected_binding is None
    assert edges == ["start"]


def test_reacquire_backs_off_between_scans_instead_of_spinning(monkeypatch):
    """With no readable device, reacquisition must wait on the stop event.

    Waiting on the event (rather than sleeping) is what lets a stop during the
    back-off end the listener immediately; a busy loop would burn a core for as
    long as the keyboard is unplugged.
    """
    scans = _detect(monkeypatch)
    scanned = _first_scan(monkeypatch)
    listener, _ = _listener()
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(listener._reacquire()), daemon=True)
    worker.start()
    try:
        # The window starts at the first scan, not at Thread.start(), so a late
        # thread start on a loaded machine cannot empty it.
        assert scanned.wait(10), "reacquire never scanned for keyboards"
        time.sleep(0.2)
        # Still waiting, not given up: a reacquire that returns at once would
        # also scan fewer than 5 times.
        assert worker.is_alive(), "reacquire returned before the stop"
        assert outcome == []
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
