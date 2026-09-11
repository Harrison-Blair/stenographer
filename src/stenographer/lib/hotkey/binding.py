# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral hotkey vocabulary and chord state machine.

``parse_binding`` turns a ``+``-joined chord of evdev ``KEY_*`` names into
codes through the platform's :class:`~stenographer.lib.platform.key_table.KeyTable`.
:class:`ChordTracker` owns the held-key union, the rising/falling edge
dispatch, and ``wait_binding_released`` (the deliverer's modifier
release-guard); it has no device I/O. A platform listener (the evdev one lives in
``stenographer.lib.platform.linux.hotkey``) subclasses it and feeds
``_key_event(device_id, code, value)`` from its reader threads. It owns no state
machine beyond edges, no cancel binding, double-tap timer, or feedback
wiring: the daemon maps edges to session actions per ``hotkey.mode``.

The pure helpers (parse_binding, chord_active, edge) and the tracker are the
unit targets; the real read loop is exercised by the uinput loopback smoke."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from stenographer.lib.platform.key_table import KeyTable

from stenographer.lib.hotkey.errors import BindingError


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
