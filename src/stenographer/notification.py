# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop notification indicator via notify-send."""

from __future__ import annotations

import logging
import pathlib
import queue
import shutil
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_HIDE = object()
"""Queue sentinel: replace the current notification with an expiring one."""


class DesktopNotification:
    """Show / hide a persistent desktop notification during dictation.

    Uses ``notify-send`` (Freedesktop Notification D-Bus spec). The
    notification ID is captured with ``-p`` and reused with ``-r`` so
    updates replace our own notification and :meth:`hide` never
    dismisses another app's. Degrades to a no-op when ``notify-send``
    is unavailable, and self-heals by re-probing after a cooldown when
    a notification attempt fails.

    All sends run on a background worker thread so callers (the hotkey
    / session path) never block on a slow notification daemon.
    """

    _retry_cooldown: float = 30.0

    def __init__(self, *, icon_path: pathlib.Path | None = None) -> None:
        self._available: bool | None = None
        self._icon_path = icon_path
        self._last_failure: float = 0.0
        self._last_id: int | None = None
        self._queue: queue.Queue[tuple[str, int] | object] = queue.Queue()
        self._worker: threading.Thread | None = None

    @staticmethod
    def probe() -> bool:
        """Return True if ``notify-send`` is on PATH. Shared with doctor."""
        return shutil.which("notify-send") is not None

    def _ensure_available(self) -> bool:
        if self._available:
            return True
        now = time.monotonic()
        if self._available is None or (now - self._last_failure) >= self._retry_cooldown:
            self._available = self.probe()
        return self._available

    # -- public API (non-blocking; work happens on the worker thread) ----

    def show_startup(self, binding: str) -> None:
        """Show a transient startup notification with the configured keybind."""
        self._enqueue(f"Ready \u2013 press {binding} to dictate", 5000)

    def show_listening(self) -> None:
        """Display 'Listening...' as a persistent notification."""
        self._enqueue("Listening\u2026", 0)

    def show_transcribing(self) -> None:
        """Display 'Transcribing...' as a persistent notification."""
        self._enqueue("Transcribing…", 0)

    def show_listening_prompt(self) -> None:
        """Display 'Listening (prompt)...' as a persistent notification."""
        self._enqueue("Listening (prompt)…", 0)

    def show_transcribing_prompt(self) -> None:
        """Display 'Transcribing (prompt)...' as a persistent notification."""
        self._enqueue("Transcribing (prompt)…", 0)

    def show_rewriting(self) -> None:
        """Display 'Rewriting with local LLM...' as a persistent notification."""
        self._enqueue("Rewriting with local LLM…", 0)

    def show_prompt_ready(self) -> None:
        """Display a transient 'Prompt ready' notification."""
        self._enqueue("Prompt ready", 3000)

    def show_prompt_failed(self) -> None:
        """Display a transient prompt-crafting-failure notification."""
        self._enqueue("Prompt-crafting failed — using raw transcript", 5000)

    def show_model_loading(self) -> None:
        self._enqueue("Loading speech model\u2009\u2014\u2009listening\u2026", 0)

    def show_model_unloaded(self) -> None:
        self._enqueue("Speech model unloaded (idle)", 5000)

    def hide(self) -> None:
        """Dismiss our notification (by replacing it with an expiring one)."""
        if not self._ensure_available():
            return
        self._ensure_worker()
        self._queue.put(_HIDE)

    def flush(self, timeout: float = 5.0) -> None:
        """Block until queued notifications have been sent (tests, shutdown)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.005)

    # -- worker -----------------------------------------------------------

    def _enqueue(self, body: str, timeout_ms: int) -> None:
        if not self._ensure_available():
            return
        self._ensure_worker()
        self._queue.put((body, timeout_ms))

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._drain, name="notification", daemon=True)
            self._worker.start()

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _HIDE:
                    self._hide_now()
                else:
                    body, timeout_ms = item  # type: ignore[misc]
                    self._send_now(body, timeout_ms)
            finally:
                self._queue.task_done()

    def _send_now(self, body: str, timeout_ms: int) -> None:
        cmd = ["notify-send", "-a", "Stenographer", "-t", str(timeout_ms), "-p"]
        if self._last_id is not None:
            cmd.extend(["-r", str(self._last_id)])
        if self._icon_path is not None:
            cmd.extend(["-i", str(self._icon_path)])
        cmd.extend(["Stenographer", body])
        proc = self._run(cmd)
        if proc is None:
            return
        out = proc.stdout
        if isinstance(out, bytes):
            text = out.decode("utf-8", "replace").strip()
            if text.isdigit():
                self._last_id = int(text)

    def _hide_now(self) -> None:
        if self._last_id is None:
            return
        cmd = [
            "notify-send",
            "-a",
            "Stenographer",
            "-t",
            "1",
            "-r",
            str(self._last_id),
            "Stenographer",
        ]
        self._run(cmd)
        self._last_id = None

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
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
            return None
