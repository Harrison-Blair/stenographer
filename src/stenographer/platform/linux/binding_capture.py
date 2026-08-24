# SPDX-License-Identifier: GPL-3.0-or-later
"""Live evdev binding capture for quick setup: non-grabbing, terminal-quiet."""

from __future__ import annotations

import contextlib
import copy
import select
import termios
import time
from typing import TYPE_CHECKING

import evdev

from stenographer.binding_capture import (
    BindingCaptureError,
    CaptureState,
    KeyEvent,
    reduce_capture,
    serialize_capture,
)
from stenographer.platform.linux.hotkey import EvdevKeyTable, auto_detect_paths

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import TextIO


@contextlib.contextmanager
def _quiet_terminal(stdin: TextIO) -> Iterator[None]:
    """Hide captured keystrokes while keeping the terminal's signal handling."""

    try:
        fd = stdin.fileno()
        original = termios.tcgetattr(fd)
    except (AttributeError, OSError, termios.error) as exc:
        raise BindingCaptureError(f"could not prepare the terminal: {exc}") from exc

    quiet = copy.deepcopy(original)
    quiet[3] &= ~(termios.ECHO | termios.ICANON)
    quiet[6][termios.VMIN] = 0
    quiet[6][termios.VTIME] = 0
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
        termios.tcsetattr(fd, termios.TCSANOW, quiet)
    except (OSError, termios.error) as exc:
        with contextlib.suppress(OSError, termios.error):
            termios.tcsetattr(fd, termios.TCSANOW, original)
        raise BindingCaptureError(f"could not prepare the terminal: {exc}") from exc

    try:
        yield
    finally:
        with contextlib.suppress(OSError, termios.error):
            termios.tcflush(fd, termios.TCIFLUSH)
        termios.tcsetattr(fd, termios.TCSANOW, original)


def capture_binding(stdin: TextIO, device_path: str | None, *, timeout: float) -> str:
    """Capture one key/chord from an explicit device or auto-detected keyboards.

    Devices are observed without grabbing them. Terminal echo and canonical input
    are disabled only for the capture window; ``ISIG`` remains untouched so Ctrl-C
    continues to raise ``KeyboardInterrupt``.
    """
    paths = [device_path] if device_path is not None else auto_detect_paths()
    return _capture_paths(stdin, paths, timeout=timeout)


def _capture_paths(stdin: TextIO, paths: Sequence[str], *, timeout: float) -> str:
    devices: list[evdev.InputDevice] = []
    for path in dict.fromkeys(paths):
        try:
            devices.append(evdev.InputDevice(path))
        except OSError as exc:
            for device in devices:
                with contextlib.suppress(OSError):
                    device.close()
            raise BindingCaptureError(f"could not open hotkey device {path}: {exc}") from exc
    if not devices:
        raise BindingCaptureError("no readable main keyboard was detected")

    state = CaptureState()
    deadline = time.monotonic() + timeout
    try:
        with _quiet_terminal(stdin):
            while not state.complete:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    state = reduce_capture(state, None)
                    break
                try:
                    ready, _, _ = select.select(devices, (), (), remaining)
                except OSError as exc:
                    raise BindingCaptureError(f"could not read hotkey devices: {exc}") from exc
                if not ready:
                    state = reduce_capture(state, None)
                    break

                events: list[tuple[float, int, str, object]] = []
                sequence = 0
                for device in ready:
                    try:
                        batch = device.read()
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        raise BindingCaptureError(
                            f"hotkey device {device.path} was lost: {exc}"
                        ) from exc
                    for event in batch:
                        if event.type == evdev.ecodes.EV_KEY:
                            events.append((event.timestamp(), sequence, device.path, event))
                            sequence += 1
                events.sort(key=lambda item: item[:2])
                for _, _, path, event in events:
                    state = reduce_capture(
                        state,
                        KeyEvent(path, event.code, event.value),
                    )
                    if state.complete:
                        break
    finally:
        for device in devices:
            with contextlib.suppress(OSError):
                device.close()

    if state.timed_out:
        raise BindingCaptureError(f"no complete binding captured within {timeout:g} seconds")
    return serialize_capture(state, EvdevKeyTable())
