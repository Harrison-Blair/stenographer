# SPDX-License-Identifier: GPL-3.0-or-later
"""PTT-only evdev hotkey listener plus its pure helpers (spec §4.9).

A clean-room simplification of the old listener: no state machine, no toggle or
hybrid mode, no cancel binding, no double-tap timer, no feedback wiring (the
daemon plays cues in its on_start/on_stop callbacks). The listener maps the
chord's rising edge to on_start and its falling edge to on_stop, and exposes
wait_binding_released as the deliverer's modifier release-guard (§4.2).

The pure helpers (parse_binding, is_main_keyboard, chord_active, edge) are the
unit targets; the real read loop is exercised by the uinput loopback smoke (§6).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import evdev

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z
_MIN_LETTER_KEYS = 10  # a real keyboard has 26 (A-Z); mice report 0-2
_NON_KEYBOARD_NAME_TOKENS = ("consumer control", "system control", "mouse", "touchpad", "trackpad")
_RESCAN_INTERVAL_SECONDS = 2.0
_REACQUIRE_INTERVAL_SECONDS = 2.0


class BindingError(ValueError):
    """Raised by parse_binding on an empty or unknown key token."""


def parse_binding(spec: str) -> frozenset[int]:
    """Parse a '+'-joined evdev chord into a frozenset of codes (ALL held = active).

    Empty spec / empty piece raises BindingError; an unknown token raises it
    naming the token. Order is irrelevant. PURE.
    """
    spec = spec.strip()
    if not spec:
        raise BindingError("hotkey.binding: empty binding")
    codes: set[int] = set()
    for piece in spec.split("+"):
        name = piece.strip()
        if not name:
            raise BindingError(f"hotkey.binding: empty key in {spec!r}")
        try:
            codes.add(evdev.ecodes.ecodes[name])
        except KeyError:
            raise BindingError(f"hotkey.binding: unknown key {name!r}") from None
    return frozenset(codes)


def is_main_keyboard(name: str, key_codes: Iterable[int]) -> bool:
    """True if *name*/*key_codes* look like a real main keyboard: not a
    consumer-control/mouse/touchpad HID, and >= _MIN_LETTER_KEYS in KEY_A..Z. PURE.
    """
    lowered = name.lower()
    if any(token in lowered for token in _NON_KEYBOARD_NAME_TOKENS):
        return False
    letters = sum(1 for code in key_codes if _KEY_A <= code <= _KEY_Z)
    return letters >= _MIN_LETTER_KEYS


def chord_active(held: set[int], chord: frozenset[int]) -> bool:
    """True iff the full (non-empty) chord is a subset of the held keys. PURE."""
    return bool(chord) and chord <= held


def edge(was_active: bool, is_active: bool) -> Literal["start", "stop"] | None:
    """Rising -> 'start', falling -> 'stop', no change -> None. PURE."""
    if is_active and not was_active:
        return "start"
    if was_active and not is_active:
        return "stop"
    return None


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


class HotkeyListener:
    """PTT evdev listener: chord rising edge -> on_start, falling edge -> on_stop.

    Listens on the configured device or every auto-detected keyboard, unioning
    held keys across HIDs under _held_lock (a press on one HID may release on
    another). Edges are computed under the shared dispatch *lock* so two readers
    cannot double-fire. The device is never grabbed: non-chord keys pass through.
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
        self._chord = chord
        self._device_path = device_path
        self._on_start = on_start
        self._on_stop = on_stop
        self._lock = lock
        self._held: set[int] = set()
        self._held_lock = threading.Lock()
        self._active = False
        self._stop_event = threading.Event()
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
        self._stop_event.set()
        for device in list(self._devices):
            with contextlib.suppress(OSError):
                device.close()
        for t in list(self._readers):
            t.join(timeout=timeout)
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._readers = []
        self._supervisor = None

    @property
    def is_running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def wait_binding_released(self, timeout: float = 1.5, poll_interval: float = 0.01) -> bool:
        """True once no binding key is held (or the listener stopped); False on
        timeout. Polls only _held under _held_lock — never the dispatch lock — so
        it cannot deadlock against a reader thread (§4.2).
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._stop_event.is_set():
                return True
            with self._held_lock:
                still_held = bool(self._chord & self._held)
            if not still_held:
                return True
            if time.monotonic() >= deadline:
                return False
            self._stop_event.wait(poll_interval)

    def _resolve_paths(self) -> list[str]:
        return [self._device_path] if self._device_path else auto_detect_paths()

    def _run(self) -> None:
        paths = self._resolve_paths()
        while not self._stop_event.is_set():
            self._devices = []
            for path in paths:
                with contextlib.suppress(OSError):
                    self._devices.append(evdev.InputDevice(path))
            if self._devices:
                for device in self._devices:
                    logger.info("hotkey: listening on %s (%s)", device.path, device.name)
                with self._held_lock:
                    self._held.clear()
                self._active = False
                self._readers = [self._spawn_reader(d) for d in self._devices]
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
        known = {device.path for device in self._devices}
        for path in auto_detect_paths():
            if self._stop_event.is_set() or path in known:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            logger.info("hotkey: hotplug — now listening on %s (%s)", path, device.name)
            self._devices.append(device)
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
        """Feed one device's key events into the shared held-set and dispatch chord
        edges. device_held tracks keys held on THIS HID so a missed release (a
        second keydown with no keyup) is synthesized; _held is the union of HIDs.
        """
        device_held: set[int] = set()
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    return
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                code, value = event.code, event.value
                after_release = stuck = False
                with self._held_lock:
                    if value == 1:
                        if code in device_held:
                            stuck = True
                            self._held.discard(code)
                            after_release = chord_active(self._held, self._chord)
                        device_held.add(code)
                        self._held.add(code)
                    elif value == 0:
                        device_held.discard(code)
                        self._held.discard(code)
                    else:
                        continue  # autorepeat (value 2) and any other value
                    is_active = chord_active(self._held, self._chord)
                if stuck:
                    self._update(after_release)
                self._update(is_active)
        except OSError as exc:
            logger.warning("hotkey: device %s lost: %s", device.path, exc)

    def _update(self, is_active: bool) -> None:
        """Dispatch a chord edge under the shared lock. The was-active read and the
        callback happen inside the lock, so two readers seeing the same press
        cannot both fire on_start.
        """
        if is_active == self._active:
            return  # racy fast path; re-checked under the dispatch lock
        with self._lock:
            transition = edge(self._active, is_active)
            if transition is None:
                return
            self._active = is_active
            if transition == "start":
                self._on_start()
            else:
                self._on_stop()
