# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-independent access to the generated key vocabulary."""

from __future__ import annotations

from stenographer.lib.hotkey.keycodes import CODE_NAMES, KEY_CODES


class StaticKeyTable:
    """:class:`~stenographer.lib.platform.key_table.KeyTable` over the generated table."""

    def code(self, name: str) -> int:
        return KEY_CODES[name]

    def name(self, code: int) -> str | None:
        return CODE_NAMES.get(code)
