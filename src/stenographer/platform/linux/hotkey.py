# SPDX-License-Identifier: GPL-3.0-or-later
"""The evdev hotkey backend: key-name table, main-keyboard auto-detection, and
the non-grabbing multi-HID listener over ``/dev/input/event*`` (spec §4.9).

``EvdevHotkeyListener`` extends the platform-neutral
:class:`~stenographer.hotkey.ChordTracker` with device opening, hotplug rescan
on read error, and per-HID reader threads. ``is_main_keyboard`` is the pure
unit target; the real read loop is exercised by the uinput loopback smoke (§6).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import evdev

from stenographer.hotkey import ChordTracker, chord_active
from stenographer.keycodes import CODE_NAMES, KEY_CODES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z
_MIN_LETTER_KEYS = 10  # a real keyboard has 26 (A-Z); mice report 0-2
_NON_KEYBOARD_NAME_TOKENS = ("consumer control", "system control", "mouse", "touchpad", "trackpad")
_RESCAN_INTERVAL_SECONDS = 2.0
_REACQUIRE_INTERVAL_SECONDS = 2.0


class EvdevKeyTable:
    """``KEY_*`` names <-> codes: the running kernel's evdev first, then the
    core :mod:`stenographer.keycodes` table.

    evdev leads so a kernel newer than the generated table still resolves its
    own keys; the fallback keeps this table a superset of the vocabulary every
    other provider speaks. The two agree today -- see
    ``tests/platform/linux/test_keycodes_drift.py``.
    """

    def code(self, name: str) -> int:
        try:
            return evdev.ecodes.ecodes[name]
        except KeyError:
            return KEY_CODES[name]

    def name(self, code: int) -> str | None:
        name = evdev.ecodes.KEY.get(code)
        if isinstance(name, list | tuple):
            name = name[0] if name else None
        if isinstance(name, str):
            return name
        return CODE_NAMES.get(code)


def is_main_keyboard(name: str, key_codes: Iterable[int]) -> bool:
    """True if *name*/*key_codes* look like a real main keyboard: not a
    consumer-control/mouse/touchpad HID, and >= _MIN_LETTER_KEYS in KEY_A..Z. PURE.
    """
    lowered = name.lower()
    if any(token in lowered for token in _NON_KEYBOARD_NAME_TOKENS):
        return False
    letters = sum(1 for code in key_codes if _KEY_A <= code <= _KEY_Z)
    return letters >= _MIN_LETTER_KEYS


def _glob_event_nodes() -> list[str]:
    """Return all /dev/input/event* paths (patchable test seam)."""
    return [str(p) for p in sorted(Path("/dev/input").glob("event*"))]


def auto_detect_paths() -> list[str]:
    """Return every main-keyboard /dev/input/event* path, most-capable first.

    All matching HIDs are listened on so that whichever interface a QMK/VIA
    keyboard routes a keypress through, the chord still fires.
    """
    candidates: list[tuple[int, str]] = []
    for path in _glob_event_nodes():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            keys = device.capabilities().get(evdev.ecodes.EV_KEY, ())
            if is_main_keyboard(device.name, keys):
                candidates.append((len(keys), path))
        finally:
            device.close()
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return [path for _, path in candidates]


def list_hotkey_devices() -> list[tuple[str, str]]:
    """Readable evdev devices with key capabilities, as setup's ``(value, label)`` pairs."""
    devices: list[tuple[str, str]] = []
    try:
        paths = evdev.list_devices()
    except OSError:
        return devices
    for path in paths:
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            try:
                has_keys = evdev.ecodes.EV_KEY in device.capabilities()
            except OSError:
                continue
            if has_keys:
                devices.append((path, f"{path}: {device.name}"))
        finally:
            with contextlib.suppress(OSError):
                device.close()
    return devices


class EvdevHotkeyListener(ChordTracker):
    """Evdev edge reporter: listens on the configured device or every
    auto-detected keyboard, unioning held keys across HIDs. The device is never
    grabbed: non-chord keys pass through.
    """

    def __init__(
        self,
        *,
        chord: frozenset[int],
        device_path: str | None,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> None:
        super().__init__(chord=chord, on_start=on_start, on_stop=on_stop, lock=lock)
        self._device_path = device_path
        self._supervisor: threading.Thread | None = None
        self._readers: list[threading.Thread] = []
        self._devices: list[evdev.InputDevice] = []

    def start(self) -> None:
        if self._supervisor is not None:
            return
        self._stop_event.clear()
        self._supervisor = threading.Thread(target=self._run, name="hotkey-listener", daemon=True)
        self._supervisor.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._transition_lock:
            self._stop_event.set()
        with self._held_lock:
            devices = list(self._devices)
            self._devices.clear()
            self._held_by_device.clear()
            self._held.clear()
        for device in devices:
            with contextlib.suppress(OSError):
                device.close()
        for t in list(self._readers):
            t.join(timeout=timeout)
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._readers = []
        self._supervisor = None
        with self._lock:
            self._active = False

    @property
    def is_running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def _resolve_paths(self) -> list[str]:
        return [self._device_path] if self._device_path else auto_detect_paths()

    def _run(self) -> None:
        paths = self._resolve_paths()
        while not self._stop_event.is_set():
            devices: list[evdev.InputDevice] = []
            for path in paths:
                with contextlib.suppress(OSError):
                    devices.append(evdev.InputDevice(path))
            if devices:
                for device in devices:
                    logger.info("hotkey: listening on %s (%s)", device.path, device.name)
                with self._held_lock:
                    self._held.clear()
                    self._held_by_device = {id(device): set() for device in devices}
                    self._devices = devices
                self._active = False
                self._readers = [self._spawn_reader(d) for d in devices]
                self._supervise()
                for t in list(self._readers):
                    t.join(timeout=0.5)
                if self._stop_event.is_set():
                    return
                logger.warning("hotkey: all keyboard devices lost; re-detecting")
            else:
                # No target device is currently openable (unplugged, stale
                # explicit path, or a permissions gap). Back off before retrying
                # so an outage cannot busy-loop the daemon: with an explicit
                # hotkey.device, _resolve_paths always yields that path, so
                # _reacquire returns instantly and never blocks (§4.9).
                logger.debug(
                    "hotkey: no openable keyboard device; retrying in %ss",
                    _REACQUIRE_INTERVAL_SECONDS,
                )
                self._stop_event.wait(_REACQUIRE_INTERVAL_SECONDS)
            paths = self._reacquire()
            if not paths:
                logger.error("hotkey: no readable keyboard device; listener exiting")
                return

    def _reacquire(self) -> list[str]:
        while not self._stop_event.is_set():
            paths = self._resolve_paths()
            if paths:
                return paths
            self._stop_event.wait(_REACQUIRE_INTERVAL_SECONDS)
        return []

    def _supervise(self) -> None:
        """Wait until every reader dies or stop is requested; while at least one
        reader lives, periodically rescan (auto-detect mode only) to pick up a
        hotplugged keyboard without disturbing an in-flight press.
        """
        next_rescan = time.monotonic() + _RESCAN_INTERVAL_SECONDS
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)
            self._readers = [t for t in self._readers if t.is_alive()]
            if not self._readers:
                return
            if self._device_path is None and time.monotonic() >= next_rescan:
                self._rescan()
                next_rescan = time.monotonic() + _RESCAN_INTERVAL_SECONDS

    def _rescan(self) -> None:
        with self._held_lock:
            known = {device.path for device in self._devices}
        for path in auto_detect_paths():
            if self._stop_event.is_set() or path in known:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            logger.info("hotkey: hotplug — now listening on %s (%s)", path, device.name)
            with self._held_lock:
                if self._stop_event.is_set():
                    device.close()
                    return
                self._devices.append(device)
                self._held_by_device[id(device)] = set()
            self._readers.append(self._spawn_reader(device))

    def _spawn_reader(self, device: evdev.InputDevice) -> threading.Thread:
        t = threading.Thread(
            target=self._reader_loop,
            args=(device,),
            name=f"hotkey-reader:{device.path}",
            daemon=True,
        )
        t.start()
        return t

    def _reader_loop(self, device: evdev.InputDevice) -> None:
        """Feed one device's key events into the shared tracker (see
        ``ChordTracker._key_event``) until the device is lost or stop is requested.
        """
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    return
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if not self._key_event(id(device), event.code, event.value):
                    return
        except OSError as exc:
            if not self._stop_event.is_set():
                logger.warning("hotkey: device %s lost: %s", device.path, exc)
        finally:
            self._device_lost(device)

    def _device_lost(self, device: evdev.InputDevice) -> None:
        """Drop one HID's state and report any resulting falling edge."""
        with self._transition_lock:
            with self._held_lock:
                self._held_by_device.pop(id(device), None)
                self._devices = [opened for opened in self._devices if opened is not device]
                self._rebuild_held()
                is_active = chord_active(self._held, self._chord)
            with contextlib.suppress(OSError):
                device.close()
            if not self._stop_event.is_set():
                self._update(is_active)
