# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import shutil

from stenographer.lib.logging.pipeline import log_failure
from stenographer.lib.platform.linux.notify import build_notify_command, bundled_icon_path, log
from stenographer.lib.platform.linux.process import spawn_detached


class NotifySendNotifier:
    """Fires notifications, degrading to a no-op when notify-send is absent."""

    def __init__(self) -> None:
        self._available = self.probe()
        self._icon = self._resolve_icon()

    @staticmethod
    def probe() -> bool:
        """True if ``notify-send`` is on PATH (shared with the M6 doctor probe)."""
        return shutil.which("notify-send") is not None

    @staticmethod
    def _resolve_icon() -> str | None:
        """The icon path once at construction, or None when it is not readable."""
        try:
            icon = bundled_icon_path()
            return str(icon) if icon.is_file() else None
        except OSError as exc:
            # An unreadable icon costs the notification its logo, never its text.
            log_failure(log, logging.DEBUG, "notify: icon_unavailable", exc, safe=True)
            return None

    def _send(self, message: str, urgency: str) -> None:
        """No-op when unavailable; failures are swallowed to log.debug (a broken
        notifier must never take the daemon down)."""
        if not self._available:
            return
        try:
            spawn_detached(build_notify_command(message, urgency, self._icon))
        except OSError as exc:
            log_failure(log, logging.DEBUG, "notify: send_failed", exc, safe=True)

    def error(self, message: str) -> None:
        """Show *message* as a critical notification, non-blocking."""
        self._send(message, "critical")

    def info(self, message: str) -> None:
        """Show *message* as a normal-urgency notification, non-blocking."""
        self._send(message, "normal")
