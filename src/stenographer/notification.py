# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop notification indicator via swaync."""

from __future__ import annotations

import logging
import pathlib
import subprocess

logger = logging.getLogger(__name__)


class DesktopNotification:
    """Show / hide a persistent desktop notification during dictation.

    Uses ``notify-send`` (Freedesktop Notification D-Bus spec, displayed
    by swaync) to show the notification, and ``swaync-client`` to dismiss
    it.  Degrades to a no-op when either tool is unavailable.
    """

    def __init__(self, *, available: bool, icon_path: pathlib.Path | None = None) -> None:
        self._available = available
        self._icon_path = icon_path

    def show_listening(self) -> None:
        """Display 'Listening...' as a persistent notification."""
        if not self._available:
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
            logger.debug("notification: notify-send failed: %s", exc)

    def hide(self) -> None:
        """Dismiss the most recent notification."""
        if not self._available:
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
            logger.debug("notification: swaync-client failed: %s", exc)
