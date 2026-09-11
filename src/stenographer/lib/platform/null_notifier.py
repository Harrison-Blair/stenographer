# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations


class NullNotifier:
    """Notifier that does nothing (mirrors ``status.NullStatusSink``)."""

    def error(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None
