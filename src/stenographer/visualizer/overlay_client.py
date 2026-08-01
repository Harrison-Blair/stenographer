# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon-side controller for the GTK4 layer-shell helper process."""

from __future__ import annotations

import contextlib
import ctypes.util
import importlib.util
import json
import logging
import os
import select
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from stenographer.visualizer.protocol import _STOP

if TYPE_CHECKING:
    import pathlib

    from stenographer.config import VisualizerConfig
    from stenographer.live import Preview

logger = logging.getLogger(__name__)

_READY_TIMEOUT_SECONDS = 3.0


def _terminate(process: subprocess.Popen[str]) -> None:
    """Stop the helper process, escalating to SIGKILL if it ignores SIGTERM."""
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()


class LayerShellOverlay:
    """JSON-lines controller for the GTK4 layer-shell helper process.

    All pipe I/O — including the lazy helper spawn and its READY handshake —
    happens on a dedicated writer thread. Public methods only enqueue, so a
    wedged GTK child can never block a caller (the session holds its lock
    across these calls, and a blocked write would deadlock the daemon).
    """

    _QUEUE_MAXSIZE = 4

    def __init__(
        self,
        cfg: VisualizerConfig,
        *,
        icon_path: pathlib.Path | None = None,
        font_path: pathlib.Path | None = None,
        on_unavailable: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._icon_path = icon_path
        self._font_path = font_path
        self._on_unavailable = on_unavailable
        self._process: subprocess.Popen[str] | None = None
        self._condition = threading.Condition()
        self._pending: deque[Any] = deque()
        self._writer: threading.Thread | None = None
        self._unavailable = False
        self._started = False
        self._closed = False

    @staticmethod
    def probe() -> bool:
        """Return whether the Python and Wayland prerequisites are visible."""
        if not os.environ.get("WAYLAND_DISPLAY") or importlib.util.find_spec("gi") is None:
            return False
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gtk, Gtk4LayerShell  # noqa: F401
        except ImportError, ValueError, AttributeError:
            return False
        return True

    def show_state(
        self,
        state: str,
        *,
        timeout_ms: int = 0,
        label: str | None = None,
    ) -> bool:
        """Queue a state change; ``False`` once the overlay is known dead.

        The helper is written to asynchronously, so this reports only that the
        overlay has not degraded yet. If the writer discovers a failure later,
        the unavailable callback replays the caller's current state through its
        fallback.
        """
        message: dict[str, Any] = {
            "command": "state",
            "state": state,
            "timeout_ms": timeout_ms,
        }
        if label is not None:
            message["label"] = label
        return self._enqueue(message, droppable=False)

    def show_levels(self, levels: list[float]) -> None:
        self._enqueue({"command": "levels", "levels": levels}, droppable=True)

    def show_preview(self, preview: Preview) -> None:
        self._enqueue(
            {
                "command": "preview",
                "stable": preview.stable,
                "provisional": preview.provisional,
            },
            droppable=False,
        )

    def clear_preview(self) -> None:
        if self._started:
            self._enqueue({"command": "preview_clear"}, droppable=False)

    def hide(self) -> bool:
        if not self._started:
            return False
        return self._enqueue(
            {"command": "state", "state": "hidden", "timeout_ms": 0},
            droppable=False,
        )

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            writer = self._writer
            # Queued messages still drain first; the bounded join below is what
            # keeps a wedged helper from holding up shutdown.
            self._pending.append(_STOP)
            self._condition.notify()

        if writer is not None:
            writer.join(timeout=2.0)
            if writer.is_alive():
                logger.warning("visualizer: overlay writer thread did not exit; killing helper")

        with self._condition:
            process = self._process
            self._process = None
        if process is None:
            return
        if writer is None or not writer.is_alive():
            try:
                process.wait(timeout=2.0)
                return
            except subprocess.TimeoutExpired:
                pass
        # Terminating also unblocks a writer wedged in a full-pipe write.
        _terminate(process)

    def _enqueue(self, message: dict[str, Any], *, droppable: bool) -> bool:
        """Hand a message to the writer thread. Never performs pipe I/O."""
        saturated = False
        with self._condition:
            if self._unavailable or self._closed:
                return False
            self._coalesce_locked(message)
            if len(self._pending) >= self._QUEUE_MAXSIZE:
                if droppable:
                    # 60 Hz level frames are stale by the time the writer
                    # drains them, so shedding them is free.
                    return True
                # A dropped state or preview would leave a wrong label on the
                # HUD. Shed a level frame, or degrade if the queue contains no
                # disposable work.
                saturated = not self._drop_oldest_levels_locked()
            if not saturated:
                self._pending.append(message)
            if self._writer is None:
                self._writer = threading.Thread(
                    target=self._run_writer,
                    name="overlay-writer",
                    daemon=True,
                )
                self._writer.start()
            self._condition.notify()
        if saturated:
            logger.warning("visualizer: overlay queue saturated; using notifications")
            self._degrade()
            return False
        return True

    def _coalesce_locked(self, message: dict[str, Any]) -> None:
        """Discard queued frames superseded by *message*.

        State, preview, and level updates all describe current values rather
        than events. Keeping only their newest pending value prevents stale HUD
        updates and makes the queue genuinely bounded when the pipe wedges.
        """
        command = message.get("command")
        if command == "state":
            superseded = {"state"}
        elif command in {"preview", "preview_clear"}:
            superseded = {"preview", "preview_clear"}
        elif command == "levels":
            superseded = {"levels"}
        else:
            return
        self._pending = deque(
            item
            for item in self._pending
            if not (isinstance(item, dict) and item.get("command") in superseded)
        )

    def _drop_oldest_levels_locked(self) -> bool:
        for index, message in enumerate(self._pending):
            if isinstance(message, dict) and message.get("command") == "levels":
                del self._pending[index]
                return True
        return False

    def _run_writer(self) -> None:
        while True:
            with self._condition:
                while not self._pending:
                    self._condition.wait()
                message = self._pending.popleft()
            if message is _STOP:
                self._write_quit()
                return
            self._write(message)

    def _write(self, message: dict[str, Any]) -> None:
        try:
            if not self._start_helper():
                return
            process = self._process
            assert process is not None
            assert process.stdin is not None
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except Exception as exc:
            # Includes failures raised out of the startup handshake; every pipe
            # error must degrade to notifications rather than kill this thread.
            logger.warning("visualizer: overlay pipe failed; using notifications: %s", exc)
            self._degrade()

    def _write_quit(self) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        with contextlib.suppress(BrokenPipeError, OSError, ValueError):
            process.stdin.write('{"command":"quit"}\n')
            process.stdin.flush()
            process.stdin.close()

    def _degrade(self) -> None:
        callback: Callable[[], None] | None
        with self._condition:
            if self._unavailable:
                return
            self._unavailable = True
            self._process = None
            self._pending = deque(item for item in self._pending if item is _STOP)
            callback = self._on_unavailable
            self._condition.notify_all()
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                logger.debug("visualizer: overlay fallback callback failed: %s", exc)

    def _start_helper(self) -> bool:
        if self._unavailable:
            return False
        if self._process is not None and self._process.poll() is None:
            return True
        if not self.probe():
            self._fail_over(None)
            return False

        command = self._build_command()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._build_environment(),
            )
        except OSError as exc:
            logger.warning("visualizer: cannot start overlay; using notifications: %s", exc)
            self._fail_over(None)
            return False

        if not self._await_ready(process):
            self._fail_over(process)
            return False
        if not self._send_configure(process):
            self._fail_over(process)
            return False

        with self._condition:
            self._process = process
            self._started = True
        logger.info("visualizer: GTK4 layer-shell overlay ready")
        return True

    def _fail_over(self, process: subprocess.Popen[str] | None) -> None:
        """Terminate any live helper, then degrade to notifications.

        The single exit path for every startup failure, so a new branch cannot
        forget to reap the subprocess before degrading.
        """
        if process is not None:
            _terminate(process)
        self._degrade()

    @staticmethod
    def _build_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "_visualizer"]
        return [sys.executable, "-m", "stenographer.visualizer", "--child"]

    def _build_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if self._font_path is not None:
            environment["STENOGRAPHER_FONT_PATH"] = str(self._font_path)
        if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
            bundled = os.path.join(sys._MEIPASS, "libgtk4-layer-shell.so.0")
            layer_shell = (
                bundled if os.path.exists(bundled) else ctypes.util.find_library("gtk4-layer-shell")
            )
        else:
            layer_shell = ctypes.util.find_library("gtk4-layer-shell")
        if layer_shell:
            preload = environment.get("LD_PRELOAD", "")
            libraries = [item for item in preload.split(":") if item]
            if layer_shell not in libraries:
                environment["LD_PRELOAD"] = ":".join([layer_shell, *libraries])
        return environment

    @staticmethod
    def _await_ready(process: subprocess.Popen[str]) -> bool:
        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_SECONDS)
        response = process.stdout.readline().strip() if readable else ""
        if response != "READY":
            logger.warning(
                "visualizer: GTK layer-shell unavailable; using notifications%s",
                f" ({response})" if response else "",
            )
            return False
        return True

    def _send_configure(self, process: subprocess.Popen[str]) -> bool:
        setup = {
            "command": "configure",
            "margin_bottom": self._cfg.margin_bottom,
            "band_count": self._cfg.frequency_bands,
            "icon_path": str(self._icon_path) if self._icon_path is not None else "",
        }
        try:
            assert process.stdin is not None
            process.stdin.write(json.dumps(setup, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            # A helper that prints READY and then dies must degrade like any
            # other pipe failure instead of raising out of the writer thread.
            logger.warning("visualizer: overlay died during setup; using notifications: %s", exc)
            return False
        return True
