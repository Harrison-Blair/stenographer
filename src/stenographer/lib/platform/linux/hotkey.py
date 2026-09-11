# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import evdev

from stenographer.lib.logging.pipeline import log_failure

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


_KEY_A = evdev.ecodes.KEY_A


_KEY_Z = evdev.ecodes.KEY_Z


_MIN_LETTER_KEYS = 10  # a real keyboard has 26 (A-Z); mice report 0-2


_NON_KEYBOARD_NAME_TOKENS = ("consumer control", "system control", "mouse", "touchpad", "trackpad")


_RESCAN_INTERVAL_SECONDS = 2.0


_REACQUIRE_INTERVAL_SECONDS = 2.0


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
        except OSError as exc:
            log_failure(logger, logging.DEBUG, "hotkey: device_skipped", exc, safe=True, path=path)
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
    except OSError as exc:
        # WARNING: this is why setup and doctor show an empty device list.
        log_failure(logger, logging.WARNING, "hotkey: enumerate_failed", exc, safe=True)
        return devices
    for path in paths:
        try:
            device = evdev.InputDevice(path)
        except OSError as exc:
            log_failure(logger, logging.DEBUG, "hotkey: device_skipped", exc, safe=True, path=path)
            continue
        try:
            try:
                has_keys = evdev.ecodes.EV_KEY in device.capabilities()
            except OSError as exc:
                log_failure(
                    logger,
                    logging.DEBUG,
                    "hotkey: capabilities_unreadable",
                    exc,
                    safe=True,
                    path=path,
                )
                continue
            if has_keys:
                devices.append((path, f"{path}: {device.name}"))
        finally:
            with contextlib.suppress(OSError):
                device.close()
    return devices
