# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop notifications: errors and short normal-urgency notices.

``notify-send`` is fired non-blocking and no-ops when absent. Only short,
caller-supplied strings are ever passed — never audio or transcript text
(the log-privacy rule). The one pure unit target is ``build_notify_command``
(mirroring cues.build_play_command); the Popen call is never mock-tested.
"""

from __future__ import annotations

import logging
import pathlib
import shutil
from importlib.resources import files

from stenographer.platform.linux.process import spawn_detached

log = logging.getLogger(__name__)


def bundled_icon_path() -> pathlib.Path:
    """The bundled app icon, anchored on the package like every other asset.

    Package-relative so the frozen bundle resolves it under
    ``_internal/stenographer/assets/`` with no ``sys._MEIPASS`` special-casing
    (see ``packaging/entry.py``).
    """
    return pathlib.Path(str(files("stenographer"))) / "assets" / "icons" / "stenographer.png"


def build_notify_command(
    message: str, urgency: str = "critical", icon: str | None = None
) -> list[str]:
    """The ``notify-send`` argv for a notification at *urgency*. PURE."""
    argv = ["notify-send", "-a", "Stenographer", "-u", urgency]
    if icon is not None:
        argv += ["-i", icon]
    return [*argv, "Stenographer", message]


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
            log.debug("notify: icon unavailable: %s", exc)
            return None

    def _send(self, message: str, urgency: str) -> None:
        """No-op when unavailable; failures are swallowed to log.debug (a broken
        notifier must never take the daemon down)."""
        if not self._available:
            return
        try:
            spawn_detached(build_notify_command(message, urgency, self._icon))
        except OSError as exc:
            log.debug("notify: send failed: %s", exc)

    def error(self, message: str) -> None:
        """Show *message* as a critical notification, non-blocking."""
        self._send(message, "critical")

    def info(self, message: str) -> None:
        """Show *message* as a normal-urgency notification, non-blocking."""
        self._send(message, "normal")
