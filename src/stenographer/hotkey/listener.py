# SPDX-License-Identifier: GPL-3.0-or-later
"""evdev read loop that drives the hotkey state machine."""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import evdev

from stenographer.hotkey.binding import HotkeyBinding
from stenographer.hotkey.state_machine import HotkeyStateMachine, Transition

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_SECONDS = 2.0
_RETRY_TIMEOUT_SECONDS = 30.0
_KEY_A = evdev.ecodes.KEY_A
_KEY_Z = evdev.ecodes.KEY_Z
_MIN_LETTER_KEYS = 10  # a real keyboard has 26 (A-Z); mice have 0-2

# Device-name substrings that mark a device as NOT a main keyboard.
# These show up as "Consumer Control", "System Control", or mouse HID
# descriptors on multi-function devices (Keychron Q1 Max, etc.).
_NON_KEYBOARD_NAME_TOKENS = (
    "consumer control",
    "system control",
    "mouse",
    "touchpad",
    "trackpad",
)


def _is_main_keyboard(device: evdev.InputDevice) -> bool:
    """Return True if ``device`` looks like a real main keyboard.

    A real keyboard has at least ``_MIN_LETTER_KEYS`` letter keys
    (KEY_A..KEY_Z) in its capability set. Mice, consumer-control
    panels, and similar HID descriptors that happen to report a few
    KEY_* codes do not pass.
    """
    name_l = device.name.lower()
    if any(token in name_l for token in _NON_KEYBOARD_NAME_TOKENS):
        return False
    try:
        caps = device.capabilities()
    except OSError:
        return False
    if evdev.ecodes.EV_KEY not in caps:
        return False
    keys = caps.get(evdev.ecodes.EV_KEY, ())
    letter_count = sum(1 for k in keys if _KEY_A <= k <= _KEY_Z)
    return letter_count >= _MIN_LETTER_KEYS


def auto_detect_paths() -> list[str]:
    """Return all main-keyboard ``/dev/input/event*`` paths.

    A QMK/VIA keyboard (e.g. Keychron Q1 Max) presents as multiple
    HID devices with the same model name. We listen on ALL of them
    so that whichever HID the firmware routes a keypress to, the
    listener still sees it.
    """
    candidates: list[tuple[Path, int]] = []
    for candidate in sorted(Path("/dev/input").glob("event*")):
        try:
            device = evdev.InputDevice(str(candidate))
        except OSError:
            continue
        try:
            if _is_main_keyboard(device):
                keys = device.capabilities().get(evdev.ecodes.EV_KEY, ())
                candidates.append((candidate, len(keys)))
        finally:
            device.close()
    candidates.sort(key=lambda c: (-c[1], c[0]))
    paths = [str(c[0]) for c in candidates]
    for path in paths:
        logger.info("hotkey: auto-detected keyboard device %s", path)
    return paths


def auto_detect_path() -> str | None:
    """Back-compat wrapper: return the single best candidate, or None."""
    paths = auto_detect_paths()
    return paths[0] if paths else None


class HotkeyListener:
    """Reads ``/dev/input/event*`` and drives the state machine.

    The listener does NOT ``EVIOCGRAB`` the device; non-chord
    keystrokes pass through to the focused window unmodified.

    v1 listens on EVERY main-keyboard HID present. A single physical
    keyboard that exposes multiple HID devices (QMK/VIA, embedded
    numeric keypad, etc.) will have all of them watched so that
    whichever interface the firmware routes a keypress through, the
    chord still fires.
    """

    def __init__(
        self,
        *,
        binding: HotkeyBinding,
        device_path: str | None,
        state_machine: HotkeyStateMachine,
        on_start: Callable[[], None],
        on_stop: Callable[[Literal["ptt", "toggle"]], None],
        on_toggle_off: Callable[[], None],
        feedback: Any,
        lock: threading.RLock | None = None,
        cancel_binding: HotkeyBinding | None = None,
        on_discard: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self._binding = binding
        self._cancel_binding = cancel_binding
        self._device_path = device_path
        self._sm = state_machine
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_toggle_off = on_toggle_off
        self._on_discard = on_discard
        self._on_cancel = on_cancel
        self._feedback = feedback
        self._lock = lock
        # Double-tap window timer; armed on the await_double_tap action.
        # Correctness against a racing second keydown comes from the state
        # machine's generation check under the dispatch lock, not from
        # Timer.cancel() (which is only hygiene).
        self._pending_timer: threading.Timer | None = None
        # Shared across all reader threads: the union of keys currently
        # held down across all listened HIDs. A QMK/VIA keyboard often
        # multiplexes the same physical key across multiple HIDs (e.g.
        # the press goes to event3, the release to event7). Tracking
        # the held set per-reader would leave the chord permanently
        # "active" on the reader that saw the press but not the
        # release, wedging the state machine.
        self._held: set[int] = set()
        self._held_lock = threading.Lock()
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
        self._cancel_pending_timer()
        for device in self._devices:
            with contextlib.suppress(OSError):
                device.close()
        for t in self._readers:
            t.join(timeout=timeout)
        if self._supervisor is not None:
            self._supervisor.join(timeout=timeout)
        self._readers = []
        self._supervisor = None

    @property
    def is_running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def _resolve_paths(self) -> list[str]:
        if self._device_path:
            return [self._device_path]
        return auto_detect_paths()

    def _run(self) -> None:
        paths = self._resolve_paths()
        deadline: float | None = None
        if not paths:
            logger.error("hotkey: no readable keyboard device found")
            return
        if self._device_path is not None:
            for p in paths:
                logger.info("hotkey: using configured device %s", p)
        # Outer loop: re-acquire ALL devices if every one is lost.
        while not self._stop_event.is_set():
            try:
                self._devices = [evdev.InputDevice(p) for p in paths]
            except (OSError, PermissionError) as exc:
                logger.warning("hotkey: cannot open devices %s: %s", paths, exc)
                paths = self._reacquire(deadline) or []
                if not paths:
                    return
                continue
            for device in self._devices:
                logger.info(
                    "hotkey: listening on %s (%s)",
                    device.path,
                    getattr(device, "name", "?"),
                )
            deadline = None
            self._cancel_pending_timer()
            # A recording waiting on the double-tap window would be orphaned
            # by the reset below (the generation bump makes its timer a
            # noop), so discard it first.
            self._dispatch(self._sm.force_discard, "device-reacquire")
            self._sm.reset()
            with self._held_lock:
                self._held.clear()
            self._spawn_readers()
            self._supervise_readers()
            self._join_readers()
            if self._stop_event.is_set():
                return
            # All readers died. Drop every device and re-detect from
            # scratch — the user may have unplugged/replugged hardware.
            logger.warning("hotkey: all keyboard devices lost; re-detecting")
            paths = self._reacquire(deadline) or []
            if not paths:
                return

    def _spawn_readers(self) -> None:
        self._readers = []
        for device in self._devices:
            t = threading.Thread(
                target=self._reader_loop,
                args=(device,),
                name=f"hotkey-reader:{device.path}",
                daemon=True,
            )
            t.start()
            self._readers.append(t)

    def _supervise_readers(self) -> None:
        """Wait until all readers are dead or stop is requested.

        When a reader dies, its device is closed; the other readers
        are not touched, so a single flaky device does not kill the
        whole hotkey pipeline.
        """
        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)
            for t in list(self._readers):
                if not t.is_alive():
                    # Find and close the dead reader's device.
                    name = t.name
                    for device in self._devices:
                        if device.path and name.endswith(device.path):
                            with contextlib.suppress(OSError):
                                device.close()
                            break
                    self._readers.remove(t)
            if not self._readers:
                return

    def _join_readers(self) -> None:
        for t in list(self._readers):
            t.join(timeout=0.5)

    def _reacquire(self, previous_deadline: float | None) -> list[str] | None:
        start = time.monotonic()
        deadline = (
            previous_deadline if previous_deadline is not None else start + _RETRY_TIMEOUT_SECONDS
        )
        while not self._stop_event.is_set():
            paths = auto_detect_paths()
            if paths:
                return paths
            if time.monotonic() >= deadline:
                logger.error("hotkey: could not reacquire a keyboard device")
                sys.exit(1)
            self._stop_event.wait(_RETRY_INTERVAL_SECONDS)
        return None

    def _reader_loop(self, device: evdev.InputDevice) -> None:
        """Read events from one device and feed the shared state machine.

        The ``held`` set is shared across all reader threads (under
        ``self._held_lock``) so that the chord is computed against the
        union of keys pressed on every listened HID. This way a key
        release delivered to a different HID than the press still
        correctly clears the held set.
        """
        chord_codes = set(self._binding.to_evdev_codes())
        cancel_codes: set[int] = set()
        if self._cancel_binding is not None:
            cancel_codes = set(self._cancel_binding.to_evdev_codes())
        # Keys currently held on THIS device. The shared self._held is the
        # union across all HIDs (a key pressed on one HID may be released on
        # another), but a genuine missed release can only be detected against
        # the single device that saw the un-released press: a second keydown
        # for a code still in device_held means this HID dropped its release.
        # A duplicate keydown mirrored from another HID is not in device_held
        # and is treated as an idempotent no-op.
        device_held: set[int] = set()
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    return
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                code = event.code
                value = event.value
                logger.debug(
                    "hotkey: %s type=EV_KEY code=%s value=%s",
                    device.path,
                    evdev.ecodes.KEY.get(code, code),
                    value,
                )
                stuck = False
                with self._held_lock:
                    if value == 1:
                        if code in device_held:
                            # This HID sent a second keydown without an
                            # intervening release, so it dropped the release
                            # and the chord may be wedged active. Synthesize
                            # a release + press.
                            stuck = True
                            self._held.discard(code)
                            active_after_release = bool(chord_codes) and chord_codes.issubset(
                                self._held
                            )
                        device_held.add(code)
                        self._held.add(code)
                    elif value == 0:
                        device_held.discard(code)
                        self._held.discard(code)
                    else:
                        continue
                    is_active = bool(chord_codes) and chord_codes.issubset(self._held)
                    cancel_pressed = (
                        value == 1
                        and code in cancel_codes
                        and cancel_codes.issubset(self._held)
                        and bool(chord_codes)
                        and chord_codes.issubset(self._held)
                    )
                if stuck:
                    logger.debug(
                        "hotkey: %s missed release for %s; synthesizing keyup+keydown",
                        device.path,
                        evdev.ecodes.KEY.get(code, code),
                    )
                    self._update_chord(active_after_release, event.timestamp(), device.path)
                if cancel_pressed:
                    self._dispatch(self._sm.on_cancel, device.path)
                    continue
                self._update_chord(is_active, event.timestamp(), device.path)
        except (OSError, PermissionError) as exc:
            logger.warning("hotkey: device %s lost: %s", device.path, exc)

    def _update_chord(self, is_active: bool, timestamp: float, source: str) -> None:
        """Emit a keydown/keyup transition if the chord state changed.

        The was-active read and the state-machine update happen inside
        the same dispatch lock, so two readers observing the same chord
        press cannot both emit a keydown.
        """
        if is_active == self._sm.is_chord_active:
            return  # racy fast path; re-checked under the dispatch lock

        def _action() -> Transition:
            was_active = self._sm.is_chord_active
            if is_active and not was_active:
                self._sm.mark_chord_active(True)
                return self._sm.on_keydown(timestamp)
            if was_active and not is_active:
                self._sm.mark_chord_active(False)
                return self._sm.on_keyup(timestamp)
            return Transition("noop", None)

        self._dispatch(_action, source)

    def _dispatch(self, action: Callable[[], Transition], source: str) -> None:
        if self._lock is not None:
            with self._lock:
                self._apply_transition(action, source)
        else:
            self._apply_transition(action, source)

    def _apply_transition(self, action: Callable[[], Transition], source: str) -> None:
        transition = action()
        logger.debug(
            "hotkey: %s transition action=%s cue=%s",
            source,
            transition.action,
            transition.cue,
        )
        if transition.cue is not None:
            try:
                self._feedback.play(transition.cue)
            except Exception as exc:
                logger.error("hotkey: feedback.play(%r) failed: %s", transition.cue, exc)
        if transition.action == "start_recording":
            self._on_start()
        elif transition.action == "stop_recording_ptt":
            self._on_stop("ptt")
        elif transition.action == "stop_recording_toggle":
            self._on_toggle_off()
        elif transition.action == "await_double_tap":
            self._arm_pending_timer()
        elif transition.action == "latch_toggle":
            self._cancel_pending_timer()
        elif transition.action == "discard_recording":
            self._cancel_pending_timer()
            if self._on_discard is not None:
                self._on_discard()
        elif transition.action == "cancel":
            self._cancel_pending_timer()
            if self._on_cancel is not None:
                self._on_cancel()

    def _arm_pending_timer(self) -> None:
        self._cancel_pending_timer()
        generation = self._sm.pending_generation
        timer = threading.Timer(
            self._sm.double_tap_window_seconds,
            lambda: self._dispatch(lambda: self._sm.on_timeout(generation), "pending-timer"),
        )
        timer.daemon = True
        timer.start()
        self._pending_timer = timer

    def _cancel_pending_timer(self) -> None:
        timer = self._pending_timer
        if timer is not None:
            timer.cancel()
            self._pending_timer = None
