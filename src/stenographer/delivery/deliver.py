# SPDX-License-Identifier: GPL-3.0-or-later
"""Final-output boundary: copy the transcript to both selections, then paste it
at the cursor with a uinput Shift+Insert chord (spec §2.7, decisions 6/7).

One injection path per session, zero per-utterance fallback: no wtype, no
per-character typing, no max_chars. The clipboard write has two backends, chosen
ONCE at daemon startup by compositor capability (see ``detect_clipboard_backend``):

- ``wl-copy`` when the compositor offers a data-control protocol (background
  clients may set the selection directly).
- ``xclip`` under XWayland otherwise (GNOME <= 46): without data-control,
  wl-copy must map an invisible focus-grabbing popup for a selection serial,
  and focus-stealing prevention blocks that popup when the requester is a
  background daemon — wl-copy hangs until timeout. An X11 client needs no
  focus to own a selection, and the compositor bridges X11 CLIPBOARD/PRIMARY
  to the Wayland selections.

The clipboard is always written and doubles as the recovery path. Pure unit
targets are ``chord_events`` and ``pick_backend``; the copy round trips and the
uinput device are covered by the integration smoke suite, never by mocks (§6).
"""

from __future__ import annotations

import enum
import logging
import os
import subprocess
import time
from typing import TYPE_CHECKING

from evdev import UInput, ecodes

from stenographer.utils.childenv import child_env

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

_SHIFT = ecodes.KEY_LEFTSHIFT
_INSERT = ecodes.KEY_INSERT
_COPY_TIMEOUT_SECONDS = 10.0
_DEVICE_SETTLE_SECONDS = 0.2

# Either protocol lets a background client set the selection without focus.
_DATA_CONTROL_GLOBALS = frozenset({"ext_data_control_manager_v1", "zwlr_data_control_manager_v1"})


class ClipboardBackend(enum.Enum):
    WL_COPY = "wl-copy"
    X11 = "x11"


def pick_backend(globals_seen: set[str], *, have_display: bool) -> ClipboardBackend:
    """Choose the clipboard backend from the compositor's registry globals. PURE.

    Data-control present → wl-copy works from a background process. Absent
    (GNOME <= 46) → the xclip/XWayland bridge, provided an X display exists;
    with neither, keep wl-copy (status quo, and its failure is already the
    safe no-chord path).
    """
    if globals_seen & _DATA_CONTROL_GLOBALS:
        return ClipboardBackend.WL_COPY
    return ClipboardBackend.X11 if have_display else ClipboardBackend.WL_COPY


def _wayland_global_interfaces() -> set[str]:
    """One registry roundtrip against the session compositor; raises on failure."""
    from pywayland.client import Display

    seen: set[str] = set()
    display = Display()
    display.connect()
    try:
        registry = display.get_registry()
        registry.dispatcher["global"] = lambda _registry, _name, interface, _version: seen.add(
            interface
        )
        if display.roundtrip() < 0:
            raise RuntimeError("Wayland registry roundtrip failed")
        registry.destroy()
    finally:
        display.disconnect()
    return seen


def detect_clipboard_backend() -> ClipboardBackend:
    """Probe the compositor once (daemon startup, never under the state lock)."""
    try:
        globals_seen = _wayland_global_interfaces()
    except Exception as exc:
        log.warning(
            "deliver: wayland registry probe failed error_type=%s; using wl-copy",
            type(exc).__name__,
        )
        return ClipboardBackend.WL_COPY
    return pick_backend(globals_seen, have_display=bool(os.environ.get("DISPLAY")))


def chord_events() -> list[tuple[int, int]]:
    """The Shift+Insert key event sequence as ``(code, value)`` press/release pairs.

    PURE. The modifier press wraps the key press+release: Insert is released
    BEFORE Shift, and Shift is never left latched. This ordering is the
    load-bearing correctness detail and the sole pure unit target.
    """
    return [(_SHIFT, 1), (_INSERT, 1), (_INSERT, 0), (_SHIFT, 0)]


def copy_both_selections(text: str) -> bool:
    """Copy *text* to the regular clipboard and the primary selection.

    Both selections because Shift+Insert reads the primary selection in some
    clients (e.g. kitty) and the regular clipboard in others. Returns True only
    if BOTH ``wl-copy`` invocations succeed; False on any failure.

    stdout/stderr go to DEVNULL rather than being captured: wl-copy forks and
    serves the selection in the background, and the forked child inherits any
    pipes, so capturing blocks until the timeout even though the clipboard is
    already set. The return code is still collected, so check=True is unchanged.
    """
    payload = text.encode("utf-8")
    for argv in (["wl-copy"], ["wl-copy", "--primary"]):
        try:
            subprocess.run(
                argv,
                input=payload,
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env(),
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            log.debug("deliver: %s failed: %s", " ".join(argv), exc)
            return False
    return True


def copy_both_selections_x11(text: str) -> bool:
    """Copy *text* to CLIPBOARD and PRIMARY via xclip under XWayland.

    xclip forks a child that serves the selection, and that child inherits any
    pipes — stdout/stderr go to DEVNULL for the same reason as wl-copy above.
    Unlike wl-copy's exit status, taking X11 selection ownership is
    fire-and-forget, so each write is confirmed by reading the selection back
    (``xclip -o`` exits without forking) and comparing bytes: True only when
    both selections verifiably hold *text*.
    """
    payload = text.encode("utf-8")
    for selection in ("clipboard", "primary"):
        argv = ["xclip", "-selection", selection]
        try:
            subprocess.run(
                argv,
                input=payload,
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env(),
            )
            readback = subprocess.run(
                [*argv, "-o"],
                check=True,
                timeout=_COPY_TIMEOUT_SECONDS,
                capture_output=True,
                env=child_env(),
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            log.debug("deliver: %s failed: %s", " ".join(argv), exc)
            return False
        if readback.stdout != payload:
            log.warning(
                "deliver: xclip %s read-back mismatch expected_bytes=%d got_bytes=%d",
                selection,
                len(payload),
                len(readback.stdout),
            )
            return False
    return True


def copy_for_backend(backend: ClipboardBackend) -> Callable[[str], bool]:
    """The copy callable for a detected backend. PURE mapping."""
    if backend is ClipboardBackend.X11:
        return copy_both_selections_x11
    return copy_both_selections


class UinputKeyboard:
    """A persistent uinput virtual keyboard that emits the paste chord.

    Exactly one device is held for the daemon's lifetime (avoids a per-utterance
    device-enumeration race and its latency). The device is opened lazily on the
    first ``send_chord`` and settled once before its first event, or the
    compositor may drop the chord. PermissionError/FileNotFoundError on
    ``/dev/uinput`` propagate — doctor owns the message (§4.13), so it must not
    silently no-op.
    """

    def __init__(self) -> None:
        self._ui: UInput | None = None

    def _ensure_device(self) -> UInput:
        if self._ui is None:
            self._ui = UInput(events={ecodes.EV_KEY: [_SHIFT, _INSERT]}, name="stenographer")
            time.sleep(_DEVICE_SETTLE_SECONDS)
        return self._ui

    def send_chord(self) -> None:
        ui = self._ensure_device()
        for code, value in chord_events():
            ui.write(ecodes.EV_KEY, code, value)
        ui.syn()

    def close(self) -> None:
        if self._ui is not None:
            self._ui.close()
            self._ui = None

    def __enter__(self) -> UinputKeyboard:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Deliverer:
    """Copy → confirm → release-guard → paste-chord, in that fixed order.

    Collaborators are injected so the daemon (M5) owns the single persistent
    device and wires the hotkey listener's ``wait_binding_released``. This is
    dependency wiring, not test mocking.
    """

    def __init__(
        self,
        *,
        keyboard: UinputKeyboard,
        wait_released: Callable[[], bool] | None = None,
        copy: Callable[[str], bool] = copy_both_selections,
    ) -> None:
        self._keyboard = keyboard
        self._wait_released = wait_released
        self._copy = copy

    def deliver(self, text: str) -> bool:
        """Deliver *text* at the cursor. Return True once the chord is sent.

        Empty text is success-shaped upstream (§4.7): return False, no side
        effects. A failed copy returns False WITHOUT sending the chord (§4.3) —
        a chord after a failed copy pastes stale clipboard content. On a
        release-wait timeout, proceed anyway (§4.2): the clipboard already holds
        the transcript as recovery.
        """
        if not text:
            return False
        if not self._copy(text):
            return False
        if self._wait_released is not None and not self._wait_released():
            log.warning(
                "deliver: binding still held after wait; proceeding "
                "(clipboard already holds the transcript)"
            )
        self._keyboard.send_chord()
        return True

    def close(self) -> None:
        self._keyboard.close()
