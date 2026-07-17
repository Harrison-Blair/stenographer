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
        """Copy ``text`` to the clipboard and the primary selection.

        Both selections are populated with the same text: the paste chord
        (Shift+Insert) reads the primary selection in some clients and the
        regular clipboard in others, so populating both is what makes the
        one chord work everywhere. Return ``True`` only if both succeed.
        """
        if not self._available:
            logger.debug("wl-copy not available")
            return False
        payload = text.encode("utf-8")
        for argv in (["wl-copy"], ["wl-copy", "--primary"]):
            try:
                # stdout/stderr go to DEVNULL rather than being captured:
                # wl-copy forks and serves the selection in the background for
                # as long as it is offered, and the forked child inherits any
                # pipes we create. subprocess.run waits for EOF on them, so
                # capturing here blocks until the timeout fires -- even though
                # wl-copy has already set the clipboard. The return code is
                # still collected, so check=True works unchanged.
                subprocess.run(
                    argv,
                    input=payload,
                    check=True,
                    timeout=10.0,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
            ) as exc:
                logger.debug("output.clipboard: %s failed: %s", " ".join(argv), exc)
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
