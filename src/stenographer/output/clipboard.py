# SPDX-License-Identifier: GPL-3.0-or-later
"""Wayland clipboard write / read via ``wl-copy`` / ``wl-paste``."""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.config import ClipboardConfig  # noqa: F401

logger = logging.getLogger(__name__)


class ClipboardManager:
    """Write the final transcript to the Wayland clipboard.

    The manager degrades to a no-op when ``wl-copy`` is not on ``PATH``.
    Each call to :meth:`copy` is
    independent; the daemon never reads from the clipboard at runtime.
    """

    def __init__(self, *, available: bool) -> None:
        self._available = available

    def copy(self, text: str) -> bool:
        """Copy ``text`` to the Wayland clipboard. Return ``True`` on success."""
        if not self._available:
            logger.debug("wl-copy not available")
            return False
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=10.0,
                capture_output=True,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            logger.debug("output.clipboard: wl-copy failed: %s", exc)
            return False
        return True

    def read(self) -> str | None:
        """Read the current clipboard text via ``wl-paste``. Used by tests."""
        if not self._available:
            return None
        try:
            proc = subprocess.run(
                ["wl-paste", "--no-newline"],
                check=True,
                capture_output=True,
                timeout=10.0,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            logger.debug("output.clipboard: wl-paste failed: %s", exc)
            return None
        text = proc.stdout.decode("utf-8")
        if text.endswith("\n"):
            text = text[:-1]
        return text

    def close(self) -> None:
        return None
