# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class ClipboardSnapshot:
    """One offered type of the clipboard, read before delivery overwrites it.

    ``data`` is another application's content, so it is excluded from the repr:
    an accidental ``%r`` in a log line names only the type and never the bytes.
    """

    mime: str
    data: bytes = field(repr=False)


type ClipboardWriter = Callable[[str], bool]
type ClipboardReader = Callable[[], ClipboardSnapshot | None]
type ClipboardRestorer = Callable[[ClipboardSnapshot], bool]
