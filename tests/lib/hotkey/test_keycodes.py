# SPDX-License-Identifier: GPL-3.0-or-later
"""The core key table loads from its generated data file and is self-consistent.

Pure and OS-free: the Linux drift test proves the data still matches evdev;
this proves the loader and the two tables agree with each other anywhere.
"""

from __future__ import annotations

from stenographer.lib.hotkey.keycodes import CODE_NAMES, KEY_CODES
from stenographer.lib.hotkey.static_key_table import StaticKeyTable


def test_tables_are_populated():
    assert len(KEY_CODES) > 0
    assert len(CODE_NAMES) > 0


def test_every_canonical_name_round_trips_through_key_codes():
    mismatched = {
        code: (name, KEY_CODES.get(name))
        for code, name in CODE_NAMES.items()
        if KEY_CODES.get(name) != code
    }
    assert mismatched == {}


def test_every_name_carries_a_key_or_button_prefix():
    prefixes = ("KEY_", "BTN_")
    assert [n for n in KEY_CODES if not n.startswith(prefixes)] == []
    assert [n for n in CODE_NAMES.values() if not n.startswith(prefixes)] == []


def test_static_key_table_round_trips_key_a():
    table = StaticKeyTable()
    assert table.name(table.code("KEY_A")) == "KEY_A"
