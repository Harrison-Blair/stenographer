# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral hotkey vocabulary and chord state machine.

``parse_binding`` turns a ``+``-joined chord of evdev ``KEY_*`` names into
codes through the platform's :class:`~stenographer.platform.base.KeyTable`.
:class:`ChordTracker` owns the held-key union, the rising/falling edge
dispatch, and ``wait_binding_released`` (the deliverer's modifier
release-guard); it has no device I/O. A platform listener (the evdev one lives in
``stenographer.platform.linux.hotkey``) subclasses it and feeds
``_key_event(device_id, code, value)`` from its reader threads. It owns no state
machine beyond edges, no hybrid mode, cancel binding, double-tap timer, or
feedback wiring: the daemon maps edges to session actions per ``hotkey.mode``.

The pure helpers (parse_binding, chord_active, edge) and the tracker are the
unit targets; the real read loop is exercised by the uinput loopback smoke.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.platform.base import KeyTable

logger = logging.getLogger(__name__)


class BindingError(ValueError):
    """Raised by parse_binding on an empty or unknown key token."""


def parse_binding(spec: str, keys: KeyTable) -> frozenset[int]:
    """Parse a '+'-joined evdev chord into a frozenset of codes (ALL held = active).

    Empty spec / empty piece raises BindingError; an unknown token raises it
    naming the token. Order is irrelevant. PURE given *keys*.
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
            codes.add(keys.code(name))
        except KeyError:
            raise BindingError(f"hotkey.binding: unknown key {name!r}") from None
    return frozenset(codes)


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


class ChordTracker:
    """Edge reporter over a held-key union: chord rising edge -> on_start,
    falling edge -> on_stop. The daemon decides what an edge means (hold vs
    toggle mode).

    Held keys are unioned across input devices under _held_lock (a press on
    one device may release on another). Edges are computed under the shared
    dispatch *lock* so two readers cannot double-fire. Subclasses register a
    device in ``_held_by_device`` and call :meth:`_key_event` per key
    transition; ``_stop_event`` is the shared shutdown flag.
    """

    def __init__(
        self,
        *,
        chord: frozenset[int],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        lock: threading.RLock,
    ) -> None:
        self._chord = chord
        self._on_start = on_start
        self._on_stop = on_stop
        self._lock = lock
        self._held: set[int] = set()
        self._held_by_device: dict[int, set[int]] = {}
        self._held_lock = threading.Lock()
        self._transition_lock = threading.Lock()
        self._active = False
        self._stop_event = threading.Event()

    def wait_binding_released(self, timeout: float = 1.5, poll_interval: float = 0.01) -> bool:
        """True once no binding key is held (or the listener stopped); False on
        timeout. Polls only _held under _held_lock — never the dispatch lock — so
        it cannot deadlock against a reader thread.
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

    def _key_event(self, device_id: int, code: int, value: int) -> bool:
        """Feed one device's key transition into the shared held state and dispatch
        chord edges. A missed release (a second keydown with no keyup) is
        synthesized; _held is derived from the per-device sets so device loss
        can remove only that device's contribution. Returns False once
        *device_id* is no longer registered (the reader should stop).
        """
        with self._transition_lock:
            after_release = stuck = False
            with self._held_lock:
                device_held = self._held_by_device.get(device_id)
                if device_held is None:
                    return False
                if value == 1:
                    if code in device_held:
                        stuck = True
                        device_held.remove(code)
                        self._rebuild_held()
                        after_release = chord_active(self._held, self._chord)
                    device_held.add(code)
                elif value == 0:
                    if code in device_held:
                        device_held.remove(code)
                    else:
                        # Some multi-interface keyboards route a key-up
                        # through a different HID from its key-down.
                        for held in self._held_by_device.values():
                            held.discard(code)
                else:
                    return True  # autorepeat (value 2) and any other value
                self._rebuild_held()
                is_active = chord_active(self._held, self._chord)
            if stuck:
                self._update(after_release)
            self._update(is_active)
        return True

    def _rebuild_held(self) -> None:
        """Rebuild the shared union. Caller holds _held_lock."""
        self._held.clear()
        for device_held in self._held_by_device.values():
            self._held.update(device_held)

    def _update(self, is_active: bool) -> None:
        """Dispatch a chord edge under the shared lock. The was-active read and the
        callback happen inside the lock, so two readers seeing the same press
        cannot both fire on_start.
        """
        if is_active == self._active:
            return  # racy fast path; re-checked under the dispatch lock
        with self._lock:
            if self._stop_event.is_set():
                return
            transition = edge(self._active, is_active)
            if transition is None:
                return
            self._active = is_active
            if transition == "start":
                self._on_start()
            else:
                self._on_stop()
