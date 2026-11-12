# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from logging import LogRecord

from stenographer.lib.platform.asr_process import AsrProcess


class AsrTransport(Protocol):
    def spawn(self, *, on_log: Callable[[LogRecord], None]) -> AsrProcess:
        """Spawn a child with a prepared-log receiver."""
        ...
