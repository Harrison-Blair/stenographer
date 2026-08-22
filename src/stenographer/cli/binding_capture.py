# SPDX-License-Identifier: GPL-3.0-or-later
"""Binding capture: the pure event-state reducer and serializer, plus the
platform delegator (the evdev capture lives in ``stenographer.platform.linux``)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

    from stenographer.platform.base import KeyTable


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
    """One device-scoped key transition; ``None`` represents timeout."""

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


def _canonical_key_name(code: int, keys: KeyTable) -> str:
    name = keys.name(code)
    if name is None:
        raise BindingCaptureError(f"captured unknown evdev key code {code}")
    return name


def serialize_capture(state: CaptureState, keys: KeyTable) -> str:
    """Serialize a completed capture as validated canonical evdev names."""

    if not state.complete:
        raise BindingCaptureError("binding capture did not complete")
    spec = "+".join(_canonical_key_name(code, keys) for code in state.codes)
    from stenographer.hotkey import BindingError, parse_binding

    try:
        parse_binding(spec, keys)
    except BindingError as exc:
        raise BindingCaptureError(str(exc)) from exc
    return spec


def capture_binding(
    stdin: TextIO,
    device_path: str | None,
    *,
    timeout: float = 15.0,
) -> str:
    """Capture one key/chord through the current platform's non-grabbing capture."""

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    from stenographer.platform import current_platform

    return current_platform().capture_binding(stdin, device_path, timeout=timeout)
