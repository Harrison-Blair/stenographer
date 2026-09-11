# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound selection menu action."""

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class MenuAction:
    """A validated sound-menu response."""

    kind: str
    index: int | None = None
