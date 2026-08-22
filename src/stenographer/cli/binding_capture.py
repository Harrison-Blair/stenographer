# SPDX-License-Identifier: GPL-3.0-or-later
"""Live evdev binding capture and its pure event-state reducer."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import select
import termios
import time
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO


class BindingCaptureError(Exception):
    """A live binding could not be captured or serialized."""


@dataclasses.dataclass(frozen=True)
class CaptureState:
    """State accumulated while capturing one key or chord."""

    held: frozenset[tuple[str, int]] = frozenset()
    codes: tuple[int, ...] = ()
    complete: bool = False
    timed_out: bool = False


@dataclasses.dataclass(frozen=True)
class KeyEvent:
    """One device-scoped evdev key transition; ``None`` represents timeout."""

    device: str
    code: int
    value: int


def reduce_capture(state: CaptureState, event: KeyEvent | None) -> CaptureState:
    """Reduce one key transition or timeout into immutable capture state. PURE."""

    if state.complete or state.timed_out:
        return state
    if event is None:
        return dataclasses.replace(state, timed_out=True)
    if event.value not in (0, 1):
        return state

    identity = (event.device, event.code)
    held = set(state.held)
    codes = state.codes
    if event.value == 1:
        if identity in held:
            return state
        held.add(identity)
        if event.code not in codes:
            codes += (event.code,)
    else:
        if identity not in held:
            return state
        held.remove(identity)

    return CaptureState(
        held=frozenset(held),
        codes=codes,
        complete=bool(codes) and not held,
    )


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


def _canonical_key_name(code: int) -> str:
    import evdev

    name = evdev.ecodes.KEY.get(code)
    if isinstance(name, list):
        name = name[0] if name else None
    if not isinstance(name, str):
        raise BindingCaptureError(f"captured unknown evdev key code {code}")
    return name


def serialize_capture(state: CaptureState) -> str:
    """Serialize a completed capture as validated canonical evdev names."""

    if not state.complete:
        raise BindingCaptureError("binding capture did not complete")
    spec = "+".join(_canonical_key_name(code) for code in state.codes)
    from stenographer.hotkey import BindingError, parse_binding

    try:
        parse_binding(spec)
    except BindingError as exc:
        raise BindingCaptureError(str(exc)) from exc
    return spec


def capture_binding(
    stdin: TextIO,
    device_path: str | None,
    *,
    timeout: float = 15.0,
) -> str:
    """Capture one key/chord from an explicit device or auto-detected keyboards.

    Devices are observed without grabbing them. Terminal echo and canonical input
    are disabled only for the capture window; ``ISIG`` remains untouched so Ctrl-C
    continues to raise ``KeyboardInterrupt``.
    """

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if device_path is None:
        from stenographer.hotkey import auto_detect_paths

        paths = auto_detect_paths()
    else:
        paths = [device_path]
    return _capture_paths(stdin, paths, timeout=timeout)


def _capture_paths(stdin: TextIO, paths: Sequence[str], *, timeout: float) -> str:
    import evdev

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
    return serialize_capture(state)
