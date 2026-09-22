# SPDX-License-Identifier: GPL-3.0-or-later
"""Thread-safe chord edges and hotkey-release waiting."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event

if TYPE_CHECKING:
    from collections.abc import Callable


from stenographer.lib.hotkey.binding import chord_active, edge

logger = logging.getLogger(__name__)


class ChordTracker:
    """Edge reporter over one held-key union and multiple named bindings.

    A binding's rising edge selects its name and reports start; its falling
    edge reports stop with that same name. The daemon decides what those edges
    mean in hold, toggle, or hybrid mode. The legacy single-chord constructor
    remains as a compatibility spelling over this same path.

    An optional cancel chord is watched over the same held-key
    union and reports its rising edge to ``on_cancel``. It is a separate
    vocabulary, not a mode: what a cancel does to a session is the daemon's
    decision, exactly as with the start/stop edges.

    Held keys are unioned across input devices under _held_lock (a press on
    one device may release on another). Edges are computed under the shared
    dispatch *lock* so two readers cannot double-fire. Subclasses register a
    device in ``_held_by_device`` and call :meth:`_key_event` per key
    transition; ``_stop_event`` is the shared shutdown flag.
    """

    def __init__(
        self,
        *,
        lock: threading.RLock,
        chord: frozenset[int] | None = None,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        bindings: dict[str, frozenset[int]] | None = None,
        on_binding_start: Callable[[str], None] | None = None,
        on_binding_stop: Callable[[str], None] | None = None,
        cancel: frozenset[int] = frozenset(),
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        if bindings is None:
            if chord is None or on_start is None or on_stop is None:
                raise TypeError("a chord and its edge callbacks are required")
            bindings = {"default": chord}

            def legacy_start(_name: str) -> None:
                on_start()

            def legacy_stop(_name: str) -> None:
                on_stop()

            on_binding_start = legacy_start
            on_binding_stop = legacy_stop
        if not bindings or on_binding_start is None or on_binding_stop is None:
            raise TypeError("bindings and their edge callbacks are required")
        self._bindings = dict(bindings)
        self._on_binding_start = on_binding_start
        self._on_binding_stop = on_binding_stop
        self._binding_keys = frozenset().union(*self._bindings.values())
        # Compatibility aliases for the original single-binding tests and the
        # evdev loss-recovery path. Production dispatch uses ``_bindings``.
        self._chord = next(iter(self._bindings.values()))
        self._on_start = on_start
        self._on_stop = on_stop
        self._lock = lock
        self._cancel = cancel
        self._on_cancel = on_cancel
        self._held: set[int] = set()
        self._held_by_device: dict[int, set[int]] = {}
        self._held_lock = threading.Lock()
        self._transition_lock = threading.Lock()
        self._active = False
        self._binding_active = {name: False for name in self._bindings}
        self._selected_binding: str | None = None
        self._cancel_active = False
        self._stop_event = threading.Event()

    def wait_binding_released(self, timeout: float = 1.5, poll_interval: float = 0.01) -> bool:
        """True once no binding key is held (or the listener stopped); False on
        timeout. Polls only _held under _held_lock — never the dispatch lock — so
        it cannot deadlock against a reader thread.
        """
        started_at = time.monotonic()
        deadline = started_at + timeout
        while True:
            if self._stop_event.is_set():
                return self._report_release(started_at, released=True, reason="listener_stopped")
            with self._held_lock:
                still_held = bool(self._binding_keys & self._held)
            if not still_held:
                return self._report_release(started_at, released=True, reason="released")
            if time.monotonic() >= deadline:
                return self._report_release(started_at, released=False, reason="timeout")
            self._stop_event.wait(poll_interval)

    @staticmethod
    def _report_release(started_at: float, *, released: bool, reason: str) -> bool:
        """Log how long the release guard actually waited, success included.

        The success case is the interesting one: a wait that is consistently
        near the timeout means the chord is being reported released late, which
        is invisible if only the timeout is ever logged.
        """
        logger.debug(
            fmt_event(
                "hotkey",
                "release_wait",
                elapsed_ms=round((time.monotonic() - started_at) * 1000.0, 1),
                released=int(released),
                reason=reason,
            )
        )
        return released

    def _key_event(self, device_id: int, code: int, value: int) -> bool:
        """Feed one device's key transition into the shared held state and dispatch
        chord edges. A missed release (a second keydown with no keyup) is
        synthesized; _held is derived from the per-device sets so device loss
        can remove only that device's contribution. Returns False once
        *device_id* is no longer registered (the reader should stop).
        """
        with self._transition_lock:
            after_release: dict[str, bool] = {}
            stuck = False
            with self._held_lock:
                device_held = self._held_by_device.get(device_id)
                if device_held is None:
                    return False
                if value == 1:
                    if code in device_held:
                        stuck = True
                        device_held.remove(code)
                        self._rebuild_held()
                        after_release = {
                            name: chord_active(self._held, chord)
                            for name, chord in self._bindings.items()
                        }
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
                active_bindings = {
                    name: chord_active(self._held, chord) for name, chord in self._bindings.items()
                }
                # Only the settled state: the synthesized release above exists
                # to re-arm the session chord, whose falling edge ends a
                # recording. A cancel key reported held twice without a release
                # is one press, not two cancels.
                cancel_active = chord_active(self._held, self._cancel)
            if stuck:
                self._update_bindings(after_release)
            self._update_bindings(active_bindings)
            self._update_cancel(cancel_active)
        return True

    def _rebuild_held(self) -> None:
        """Rebuild the shared union. Caller holds _held_lock."""
        self._held.clear()
        for device_held in self._held_by_device.values():
            self._held.update(device_held)

    def _reset_edges(self) -> None:
        """Forget both chords' edge state so the next press is a rising edge."""
        self._active = False
        self._binding_active = {name: False for name in self._bindings}
        self._selected_binding = None
        self._cancel_active = False

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

    def _update_bindings(self, active: dict[str, bool]) -> None:
        """Dispatch all profile chords through one selected-session state."""

        with self._lock:
            if self._stop_event.is_set():
                return
            selected = self._selected_binding
            if selected is not None and not active[selected]:
                self._binding_active[selected] = False
                self._selected_binding = None
                self._active = False
                self._on_binding_stop(selected)
            if self._selected_binding is None:
                for name in self._bindings:
                    if active[name] and not self._binding_active[name]:
                        self._binding_active[name] = True
                        self._selected_binding = name
                        self._active = name == next(iter(self._bindings))
                        self._on_binding_start(name)
                        break
            for name, is_active in active.items():
                self._binding_active[name] = is_active

    def _update_cancel(self, is_active: bool) -> None:
        """Dispatch the cancel chord's rising edge under the shared dispatch lock.

        Only the rising edge carries meaning: a cancel is an instant, never a
        held state, so the falling edge merely re-arms the next press. Sharing
        the dispatch lock with :meth:`_update` keeps a cancel from interleaving
        with a session edge the daemon is still handling.
        """
        if is_active == self._cancel_active:
            return  # racy fast path; re-checked under the dispatch lock
        with self._lock:
            if self._stop_event.is_set():
                return
            transition = edge(self._cancel_active, is_active)
            if transition is None:
                return
            self._cancel_active = is_active
            if transition == "start" and self._on_cancel is not None:
                self._on_cancel()
