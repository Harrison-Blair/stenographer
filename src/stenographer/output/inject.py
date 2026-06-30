# SPDX-License-Identifier: GPL-3.0-or-later
"""Wayland text injection via ``wtype``.

See ``spec/05-text-output.md`` for the full behaviour contract. The
Injector degrades to a no-op when ``wtype`` is not on ``PATH``; on a
runtime failure the session falls back to the clipboard, which is
always populated independently.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class Injector:
    """Type text at the cursor via ``wtype``.

    The Injector is a stateless thin wrapper around ``subprocess.run``;
    it owns no resources and :meth:`close` is a no-op.
    """

    def __init__(
        self,
        *,
        available: bool,
        append_trailing_space: bool = True,
        max_chars: int = 4096,
    ) -> None:
        self._available = available
        self._append_trailing_space = append_trailing_space
        self._max_chars = max_chars

    def type_text(self, text: str, *, raw: bool = False) -> bool:
        """Type ``text`` at the focused window. Return ``True`` on success.

        When ``raw=True``, bypass ``_prepare()`` so that leading
        whitespace, casing, and length are passed through unchanged.
        """
        if not self._available:
            logger.warning("output.inject: wtype not available; skipping")
            return False
        if not raw:
            text = self._prepare(text)
        if not text:
            return True
        try:
            subprocess.run(
                ["wtype", "--", text],
                check=True,
                timeout=5.0,
                capture_output=True,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            rc = exc.returncode if isinstance(exc, subprocess.CalledProcessError) else -1
            stderr = (
                exc.stderr.decode("utf-8", "replace")
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
                else ""
            )
            logger.error(
                "output.inject: wtype failed (rc=%s, stderr=%s); falling back to clipboard (%s)",
                rc,
                stderr,
                type(exc).__name__,
            )
            return False
        return True

    def _prepare(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if len(text) > self._max_chars:
            logger.warning(
                "output.inject: truncating transcript from %d to %d chars",
                len(text),
                self._max_chars,
            )
            text = text[: self._max_chars]
        if self._append_trailing_space:
            text += " "
        return text

    def close(self) -> None:
        return None
