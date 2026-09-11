# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class _ClosableBackend(Protocol):
    def close(self) -> None: ...
