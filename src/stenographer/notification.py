# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop notification indicator via swaync."""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
import time

logger = logging.getLogger(__name__)


class DesktopNotification:
    """Show / hide a persistent desktop notification during dictation.

    Uses ``notify-send`` (Freedesktop Notification D-Bus spec, displayed
    by swaync) to show the notification, and ``swaync-client`` to dismiss
    it.  Degrades to a no-op when either tool is unavailable, and
    self-heals by re-probing after a cooldown when a notification
    attempt fails.
    """

    _retry_cooldown: float = 30.0

    def __init__(self, *, icon_path: pathlib.Path | None = None) -> None:
        self._available: bool | None = None
        self._icon_path = icon_path
        self._last_failure: float = 0.0

    def _probe(self) -> bool:
        return shutil.which("swaync-client") is not None and shutil.which("notify-send") is not None

    def _ensure_available(self) -> bool:
        if self._available:
            return True
        now = time.monotonic()
        if self._available is None or (now - self._last_failure) >= self._retry_cooldown:
            self._available = self._probe()
        return self._available

    def show_startup(self, binding: str) -> None:
        """Show a transient startup notification with the configured keybind."""
        if not self._ensure_available():
            return
        try:
            cmd = [
                "notify-send",
                "-a",
                "Stenographer",
                "-t",
                "5000",
            ]
            if self._icon_path is not None:
                cmd.extend(["-i", str(self._icon_path)])
            cmd.extend(["Stenographer", f"Ready \u2013 press {binding} to dictate"])
            subprocess.run(
                cmd,
                check=True,
                timeout=5.0,
                capture_output=True,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            self._available = False
            self._last_failure = time.monotonic()
            logger.debug("notification: notify-send failed: %s", exc)

    def show_listening(self) -> None:
        """Display 'Listening...' as a persistent notification."""
        if not self._ensure_available():
            return
        try:
            cmd = [
                "notify-send",
                "-a",
                "Stenographer",
                "-t",
                "0",
            ]
            if self._icon_path is not None:
                cmd.extend(["-i", str(self._icon_path)])
            cmd.extend(["Stenographer", "Listening\u2026"])
            subprocess.run(
                cmd,
                check=True,
                timeout=5.0,
                capture_output=True,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            self._available = False
            self._last_failure = time.monotonic()
            logger.debug("notification: notify-send failed: %s", exc)

    def hide(self) -> None:
        """Dismiss the most recent notification."""
        if not self._ensure_available():
            return
        try:
            subprocess.run(
                ["swaync-client", "--close-latest"],
                check=True,
                timeout=2.0,
                capture_output=True,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            self._available = False
            self._last_failure = time.monotonic()
            logger.debug("notification: swaync-client failed: %s", exc)
