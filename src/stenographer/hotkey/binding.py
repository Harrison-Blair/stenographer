# SPDX-License-Identifier: GPL-3.0-or-later
"""Parse the hotkey binding string from config into a normalised form."""

from __future__ import annotations

import evdev

from stenographer.errors import ConfigError

_VALID_KEY_NAMES: frozenset[str] = frozenset(evdev.ecodes.KEY.values())


class HotkeyBinding:
    """An ordered, canonicalised set of evdev key names forming a chord.

    A single key is just a one-element tuple. A chord is a tuple with N
    elements. The binding is canonicalised by sorting the names
    case-insensitively, so ``"KEY_A+KEY_LEFTCTRL"`` and
    ``"KEY_LEFTCTRL+KEY_A"`` compare equal.
    """

    __slots__ = ("_keys",)

    def __init__(self, keys: tuple[str, ...]) -> None:
        if not keys:
            raise ConfigError("hotkey binding is empty")
        for name in keys:
            if name not in _VALID_KEY_NAMES:
                raise ConfigError(f"unknown evdev key: {name!r}")
        self._keys = tuple(sorted(keys, key=str.lower))

    @classmethod
    def parse(cls, s: str) -> HotkeyBinding:
        s = s.strip()
        if not s:
            raise ConfigError("hotkey binding is empty")
        parts = tuple(p.strip() for p in s.split("+"))
        for piece in parts:
            if not piece:
                raise ConfigError(f"hotkey binding has empty piece in {s!r}")
        return cls(parts)

    @property
    def keys(self) -> tuple[str, ...]:
        return self._keys

    def to_evdev_codes(self) -> tuple[int, ...]:
        return tuple(getattr(evdev.ecodes, name) for name in self._keys)

    def matches(self, event_keys: set[int]) -> bool:
        return set(self.to_evdev_codes()) == event_keys

    def __str__(self) -> str:
        return "+".join(self._keys)

    def __repr__(self) -> str:
        return f"HotkeyBinding({self._keys!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HotkeyBinding):
            return NotImplemented
        return self._keys == other._keys

    def __hash__(self) -> int:
        return hash(self._keys)
