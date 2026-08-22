# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated core key table must still match the installed evdev.

``stenographer.keycodes`` is emitted by ``scripts/gen_keycodes.py`` from
``evdev.ecodes`` so every provider speaks one ``KEY_*`` vocabulary. This proves
the checked-in data has not drifted from the source it was generated against,
and that the Linux table's evdev-first lookup agrees with it entry for entry.

Linux-only: the directory conftest ignores it elsewhere.
"""

from __future__ import annotations

import evdev

from stenographer.keycodes import CODE_NAMES, KEY_CODES, StaticKeyTable
from stenographer.platform.linux.hotkey import EvdevKeyTable


def test_generated_codes_match_evdev():
    mismatched = {
        name: (code, evdev.ecodes.ecodes.get(name))
        for name, code in KEY_CODES.items()
        if evdev.ecodes.ecodes.get(name) != code
    }
    assert mismatched == {}


def test_generated_table_covers_every_evdev_key_and_button_name():
    expected = {
        name
        for name, value in evdev.ecodes.ecodes.items()
        if name.startswith(("KEY_", "BTN_")) and isinstance(value, int)
    }
    assert expected - set(KEY_CODES) == set()


def test_generated_names_match_the_linux_table():
    evdev_table = EvdevKeyTable()
    mismatched = {
        code: (name, evdev_table.name(code))
        for code, name in CODE_NAMES.items()
        if evdev_table.name(code) != name
    }
    assert mismatched == {}


def test_both_tables_resolve_every_name_identically():
    static = StaticKeyTable()
    evdev_table = EvdevKeyTable()
    mismatched = {
        name: (static.code(name), evdev_table.code(name))
        for name in KEY_CODES
        if static.code(name) != evdev_table.code(name)
    }
    assert mismatched == {}
