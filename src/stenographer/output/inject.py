# SPDX-License-Identifier: GPL-3.0-or-later
"""Text injection at the cursor.

Two backends are supported, selected by display-server session type:
``wtype`` on Wayland and ``xdotool`` on X11. The Injector degrades to a
no-op when ``backend`` is ``None`` (no injection tool on ``PATH``); on a
runtime failure the session falls back to the clipboard, which is
always populated independently.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)

InjectorBackend = Literal["wtype", "xdotool"]


class Injector:
    """Type text at the cursor via ``wtype`` (Wayland) or ``xdotool`` (X11).

    The Injector is a stateless thin wrapper around ``subprocess.run``;
    it owns no resources and :meth:`close` is a no-op.
    """

    def __init__(
        self,
        *,
        backend: InjectorBackend | None,
        append_trailing_space: bool = True,
        max_chars: int = 4096,
    ) -> None:
        self._backend = backend
        self._append_trailing_space = append_trailing_space
        self._max_chars = max_chars

    def type_text(self, text: str, *, raw: bool = False) -> bool:
        """Type ``text`` at the focused window. Return ``True`` on success.

        When ``raw=True``, bypass ``_prepare()`` so that leading
        whitespace, casing, and length are passed through unchanged.
        """
        if self._backend is None:
            logger.warning("output.inject: no injection backend available; skipping")
            return False
        if not raw:
            text = self._prepare(text)
        if not text:
            return True
        if self._backend == "wtype":
            argv = ["wtype", "--", text]
        else:
            argv = ["xdotool", "type", "--clearmodifiers", "--", text]
        try:
            subprocess.run(
                argv,
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
                "output.inject: %s failed (rc=%s, stderr=%s); falling back to clipboard (%s)",
                self._backend,
                rc,
                stderr,
                type(exc).__name__,
            )
            return False
        return True

    def paste(self) -> bool:
        """Simulate Shift+Insert. Return ``True`` on success.

        Used by paste-mode injection: the Session copies text to the
        clipboard first, then calls this to paste it at the cursor.
        Shift+Insert is the chord validated across the target apps; it
        reads the primary selection in some clients (kitty) and the
        regular clipboard in others, which is why
        :meth:`ClipboardManager.copy` populates both.
        """
        if self._backend is None:
            logger.warning("output.inject: no injection backend available; cannot paste")
            return False
        if self._backend == "wtype":
            argv = ["wtype", "-M", "shift", "-k", "Insert", "-m", "shift"]
        else:
            argv = ["xdotool", "key", "--clearmodifiers", "shift+Insert"]
        try:
            subprocess.run(
                argv,
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
                "output.inject: %s paste failed (rc=%s, stderr=%s, exc=%s)",
                self._backend,
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
