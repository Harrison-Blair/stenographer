# SPDX-License-Identifier: GPL-3.0-or-later
"""Final-output boundary: copy the transcript to both Wayland selections, then
paste it at the cursor with a uinput Shift+Insert chord (spec §2.7, decisions 6/7).

One injection path, zero fallback: no wtype, no per-character typing, no
max_chars. The clipboard is always written and doubles as the recovery path.
The only pure unit target is ``chord_events``; the wl-copy round trip and the
uinput device are covered by the integration smoke suite, never by mocks (§6).
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

from evdev import UInput, ecodes

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

_SHIFT = ecodes.KEY_LEFTSHIFT
_INSERT = ecodes.KEY_INSERT
_COPY_TIMEOUT_SECONDS = 10.0
_DEVICE_SETTLE_SECONDS = 0.2


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
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            log.debug("deliver: %s failed: %s", " ".join(argv), exc)
            return False
    return True


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
