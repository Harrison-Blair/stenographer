# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import evdev

from stenographer.lib.hotkey.keycodes import CODE_NAMES, KEY_CODES


class EvdevKeyTable:
    """``KEY_*`` names <-> codes: the running kernel's evdev first, then the
    core :mod:`stenographer.lib.hotkey.keycodes` table.

    evdev leads so a kernel newer than the generated table still resolves its
    own keys; the fallback keeps this table a superset of the vocabulary every
    other provider speaks. The two agree today -- see
    ``tests/platform/linux/test_keycodes_drift.py``.
    """

    def code(self, name: str) -> int:
        try:
            return evdev.ecodes.ecodes[name]
        except KeyError:
            return KEY_CODES[name]

    def name(self, code: int) -> str | None:
        name = evdev.ecodes.KEY.get(code)
        if isinstance(name, list | tuple):
            name = name[0] if name else None
        if isinstance(name, str):
            return name
        return CODE_NAMES.get(code)
