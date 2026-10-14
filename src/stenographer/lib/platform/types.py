# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.platform.clipboard_snapshot import ClipboardSnapshot


type ClipboardWriter = Callable[[str], bool]
type ClipboardReader = Callable[[], ClipboardSnapshot | None]
type ClipboardRestorer = Callable[[ClipboardSnapshot], bool]
