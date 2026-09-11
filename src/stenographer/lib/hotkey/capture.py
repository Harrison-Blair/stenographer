# SPDX-License-Identifier: GPL-3.0-or-later
"""Binding capture vocabulary: the pure event-state reducer and serializer.

Core data shared by the CLI setup flow and every platform provider (the live
capture backends live in ``stenographer.lib.platform.*``)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.lib.platform.key_table import KeyTable

from stenographer.lib.hotkey.capture_records import CaptureState, KeyEvent
from stenographer.lib.hotkey.errors import BindingCaptureError


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
    from stenographer.lib.hotkey.binding import parse_binding
    from stenographer.lib.hotkey.errors import BindingError

    try:
        parse_binding(spec, keys)
    except BindingError as exc:
        raise BindingCaptureError(str(exc)) from exc
    return spec
