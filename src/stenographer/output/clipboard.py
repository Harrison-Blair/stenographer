# SPDX-License-Identifier: GPL-3.0-or-later
"""Clipboard write / read.

Two backends are supported, selected by display-server session type:
``wl-copy`` / ``wl-paste`` on Wayland and ``xclip`` / ``xsel`` on X11.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from stenographer.config import ClipboardConfig  # noqa: F401

logger = logging.getLogger(__name__)

ClipboardBackend = Literal["wl-clipboard", "xclip", "xsel"]


class ClipboardManager:
    """Write the final transcript to the clipboard.

    The manager degrades to a no-op when ``backend`` is ``None`` (no
    clipboard tool on ``PATH``). Each call to :meth:`copy` is
    independent; the daemon never reads from the clipboard at runtime.
    """

    def __init__(self, *, backend: ClipboardBackend | None) -> None:
        self._backend = backend

    def _copy_argv(self, *, primary: bool) -> list[str]:
        if self._backend == "wl-clipboard":
            return ["wl-copy", "--primary"] if primary else ["wl-copy"]
        if self._backend == "xclip":
            return ["xclip", "-selection", "primary" if primary else "clipboard"]
        # xsel
        return ["xsel", "--primary" if primary else "--clipboard", "--input"]

    def _read_argv(self) -> list[str]:
        if self._backend == "wl-clipboard":
            return ["wl-paste", "--no-newline"]
        if self._backend == "xclip":
            return ["xclip", "-selection", "clipboard", "-o"]
        # xsel
        return ["xsel", "--clipboard", "--output"]

    def copy(self, text: str, *, primary: bool = False) -> bool:
        """Copy ``text`` to the clipboard; with *primary*, the primary selection too.

        The paste chord (Shift+Insert) reads the primary selection in some
        clients and the regular clipboard in others, so the paste paths pass
        ``primary=True`` -- populating both is what makes the one chord work
        everywhere, and the call returns ``True`` only if both succeed.

        It defaults to False because the primary selection is the user's
        mouse-selection buffer, not ours: ``transcribe FILE`` merely stashes a
        transcript the user never asked to have pasted, so clobbering their
        selection would be pure collateral damage. Every path the user is
        expected to paste from -- including the fallback copies, which exist
        precisely to be pasted by hand -- passes ``primary=True``.
        """
        if self._backend is None:
            logger.debug("clipboard backend not available")
            return False
        payload = text.encode("utf-8")
        argvs = [self._copy_argv(primary=False)]
        if primary:
            argvs.append(self._copy_argv(primary=True))
        for argv in argvs:
            try:
                # stdout/stderr go to DEVNULL rather than being captured:
                # the clipboard tool forks and serves the selection in the
                # background for as long as it is offered (wl-copy always;
                # xclip/xsel likewise unless told to detach), and the forked
                # child inherits any pipes we create. subprocess.run waits for
                # EOF on them, so capturing here blocks until the timeout fires
                # -- even though the clipboard has already been set. The return
                # code is still collected, so check=True works unchanged.
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
        """Read the current clipboard text. Used by tests."""
        if self._backend is None:
            return None
        try:
            proc = subprocess.run(
                self._read_argv(),
                check=True,
                capture_output=True,
                timeout=10.0,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ) as exc:
            logger.debug("output.clipboard: read failed: %s", exc)
            return None
        text = proc.stdout.decode("utf-8")
        if text.endswith("\n"):
            text = text[:-1]
        return text

    def close(self) -> None:
        return None
