# SPDX-License-Identifier: GPL-3.0-or-later
"""Wayland status overlay and microphone spectrum analysis.

The daemon-side :class:`StatusIndicator` owns a small helper process that
renders GTK4 on the layer shell. Audio callback work is limited to copying the
latest mono block into a one-slot queue; FFT analysis and GUI IPC happen on a
dedicated worker thread. If GTK, layer shell, or Wayland is unavailable, the
existing Freedesktop notification backend remains fully functional.
"""

from __future__ import annotations

import contextlib
import ctypes.util
import html
import importlib.util
import itertools
import json
import logging
import math
import os
import queue
import select
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from stenographer._version import __version__
from stenographer.notification import DesktopNotification

if TYPE_CHECKING:
    import pathlib

    from stenographer.config import VisualizerConfig

logger = logging.getLogger(__name__)

_STOP = object()
_READY_TIMEOUT_SECONDS = 3.0


def analyze_frequency_bands(
    samples: np.ndarray,
    sample_rate: int,
    band_count: int,
    min_frequency: float,
    max_frequency: float,
) -> np.ndarray:
    """Return logarithmic frequency-band levels normalized to ``0.0..1.0``.

    A Hann-windowed real FFT is mapped from -60 dBFS (empty bar) to 0 dBFS
    (full bar). The highest spectral bin in each logarithmic band drives that
    band, which keeps speech harmonics legible in a compact display.
    """
    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if mono.size < 2 or sample_rate <= 0 or band_count <= 0:
        return np.zeros(max(0, band_count), dtype=np.float32)
    mono = np.nan_to_num(mono, copy=False)
    mono = mono - float(np.mean(mono))
    if not np.any(mono):
        return np.zeros(band_count, dtype=np.float32)

    fft_size = max(512, 1 << math.ceil(math.log2(mono.size)))
    window = np.hanning(mono.size).astype(np.float32)
    coherent_gain = max(float(np.sum(window)) / 2.0, np.finfo(np.float32).eps)
    magnitudes = np.abs(np.fft.rfft(mono * window, n=fft_size)) / coherent_gain
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)

    nyquist = sample_rate / 2.0
    low = max(float(min_frequency), sample_rate / fft_size)
    high = min(float(max_frequency), nyquist)
    if high <= low:
        return np.zeros(band_count, dtype=np.float32)

    edges = np.geomspace(low, high, band_count + 1)
    levels = np.zeros(band_count, dtype=np.float32)
    for index, (edge_low, edge_high) in enumerate(itertools.pairwise(edges)):
        if index == band_count - 1:
            mask = (frequencies >= edge_low) & (frequencies <= edge_high)
        else:
            mask = (frequencies >= edge_low) & (frequencies < edge_high)
        if not np.any(mask):
            continue
        amplitude = float(np.max(magnitudes[mask]))
        dbfs = 20.0 * math.log10(max(amplitude, 1e-6))
        levels[index] = np.clip((dbfs + 60.0) / 60.0, 0.0, 1.0)
    return levels


class SpectrumAnalyzer:
    """Analyze only the newest audio block on a background thread."""

    def __init__(
        self,
        *,
        band_count: int,
        min_frequency: float,
        max_frequency: float,
        on_levels: Callable[[list[float]], None],
    ) -> None:
        self._band_count = band_count
        self._min_frequency = min_frequency
        self._max_frequency = max_frequency
        self._on_levels = on_levels
        self._queue: queue.Queue[tuple[np.ndarray, int] | object] = queue.Queue(maxsize=1)
        self._active = threading.Event()
        self._reset = threading.Event()
        self._mutex = threading.Lock()
        self._closed = False
        # Only the worker thread touches _smoothed; other threads ask for a
        # reset instead, so a zeroing can never be lost inside an update.
        self._smoothed = np.zeros(band_count, dtype=np.float32)
        self._worker = threading.Thread(
            target=self._run,
            name="spectrum-analyzer",
            daemon=True,
        )
        self._worker.start()

    def set_active(self, active: bool) -> None:
        self._reset.set()
        if active:
            self._active.set()
            return
        self._active.clear()
        with self._mutex:
            self._discard_pending()

    def submit(self, samples: np.ndarray, sample_rate: int) -> None:
        """Copy and enqueue a block without waiting for the analyzer."""
        if not self._active.is_set() or self._closed:
            return
        packet = (np.asarray(samples, dtype=np.float32).reshape(-1).copy(), sample_rate)
        # The mutex keeps discard-then-put atomic against close(), which would
        # otherwise see its stop sentinel discarded by a racing submit.
        with self._mutex:
            if self._closed:
                return
            try:
                self._queue.put_nowait(packet)
                return
            except queue.Full:
                pass
            self._discard_pending()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(packet)

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            self._active.clear()
            self._discard_pending()
            self._queue.put_nowait(_STOP)
        self._worker.join(timeout=2.0)
        if self._worker.is_alive():
            logger.warning("visualizer: spectrum analyzer thread did not exit")

    def _discard_pending(self) -> None:
        with contextlib.suppress(queue.Empty):
            self._queue.get_nowait()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if self._reset.is_set():
                self._reset.clear()
                self._smoothed.fill(0.0)
            if not self._active.is_set():
                continue
            samples, sample_rate = item  # type: ignore[misc]
            levels = analyze_frequency_bands(
                samples,
                sample_rate,
                self._band_count,
                self._min_frequency,
                self._max_frequency,
            )
            # A responsive attack and short release make plosives and pauses
            # visually distinct at the target 60 Hz capture cadence.
            coefficient = np.where(levels >= self._smoothed, 0.84, 0.32)
            self._smoothed += coefficient * (levels - self._smoothed)
            smoothed = self._smoothed.tolist()
            if not self._active.is_set():
                # Deactivated while this block was analyzed; publishing now
                # would freeze pre-cancel bars under a "Transcribing" label.
                continue
            try:
                self._on_levels(smoothed)
            except Exception as exc:
                logger.debug("visualizer: level consumer failed: %s", exc)


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

    def show_preview(self, stable: str, provisional: str) -> None:
        self._enqueue(
            {
                "command": "preview",
                "stable": stable,
                "provisional": provisional,
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
            self._degrade()
            return False

        if getattr(sys, "frozen", False):
            command = [sys.executable, "_visualizer"]
        else:
            command = [sys.executable, "-m", "stenographer.visualizer", "--child"]
        try:
            environment = os.environ.copy()
            if self._font_path is not None:
                environment["STENOGRAPHER_FONT_PATH"] = str(self._font_path)
            if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
                bundled = os.path.join(sys._MEIPASS, "libgtk4-layer-shell.so.0")
                layer_shell = (
                    bundled
                    if os.path.exists(bundled)
                    else ctypes.util.find_library("gtk4-layer-shell")
                )
            else:
                layer_shell = ctypes.util.find_library("gtk4-layer-shell")
            if layer_shell:
                preload = environment.get("LD_PRELOAD", "")
                libraries = [item for item in preload.split(":") if item]
                if layer_shell not in libraries:
                    environment["LD_PRELOAD"] = ":".join([layer_shell, *libraries])
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=environment,
            )
        except OSError as exc:
            logger.warning("visualizer: cannot start overlay; using notifications: %s", exc)
            self._degrade()
            return False

        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_SECONDS)
        response = process.stdout.readline().strip() if readable else ""
        if response != "READY":
            logger.warning(
                "visualizer: GTK layer-shell unavailable; using notifications%s",
                f" ({response})" if response else "",
            )
            _terminate(process)
            self._degrade()
            return False

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
            _terminate(process)
            self._degrade()
            return False

        with self._condition:
            self._process = process
            self._started = True
        logger.info("visualizer: GTK4 layer-shell overlay ready")
        return True


class StatusIndicator:
    """Prefer the spectrum overlay and transparently fall back to notify-send."""

    def __init__(
        self,
        *,
        cfg: VisualizerConfig,
        icon_path: pathlib.Path | None = None,
        font_path: pathlib.Path | None = None,
    ) -> None:
        self._desktop = DesktopNotification(icon_path=icon_path)
        self._state_lock = threading.RLock()
        self._desktop_visible = False
        self._fallback_show: Callable[[], None] | None = None
        self._fallback_replayed = False
        self._closed = False
        self._analyzer = SpectrumAnalyzer(
            band_count=cfg.frequency_bands,
            min_frequency=cfg.min_frequency,
            max_frequency=cfg.max_frequency,
            on_levels=self._show_levels,
        )
        self._overlay = (
            LayerShellOverlay(
                cfg,
                icon_path=icon_path,
                font_path=font_path,
                on_unavailable=self._overlay_unavailable,
            )
            if cfg.enabled
            else None
        )

    @staticmethod
    def overlay_probe() -> bool:
        return LayerShellOverlay.probe()

    def show_startup(self, binding: str) -> None:
        with self._state_lock:
            self._show_overlay_or_desktop(
                "ready",
                5000,
                lambda: self._desktop.show_startup(binding),
            )

    def show_listening(self) -> None:
        with self._state_lock:
            shown = self._show_overlay_or_desktop(
                "listening",
                0,
                self._desktop.show_listening,
            )
            self._analyzer.set_active(shown)

    def show_transcribing(self) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "transcribing",
                0,
                self._desktop.show_transcribing,
            )

    def show_model_loading(self) -> None:
        with self._state_lock:
            shown = self._show_overlay_or_desktop(
                "loading",
                0,
                self._desktop.show_model_loading,
            )
            self._analyzer.set_active(shown)

    def show_model_unloaded(self) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "unloaded",
                5000,
                self._desktop.show_model_unloaded,
            )

    def show_update_available(self, version: str) -> None:
        with self._state_lock:
            self._analyzer.set_active(False)
            self._show_overlay_or_desktop(
                "update_available",
                10000,
                lambda: self._desktop.show_update_available(version),
                label=f"Release v{version} available",
            )

    def publish_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        self._analyzer.submit(samples, sample_rate)

    def show_preview(self, stable: str, provisional: str) -> None:
        """Update only the GTK overlay; transcript text is never notified."""
        if self._overlay is not None:
            self._overlay.show_preview(stable, provisional)

    def clear_preview(self) -> None:
        if self._overlay is not None:
            self._overlay.clear_preview()

    def hide(self) -> None:
        with self._state_lock:
            self._fallback_show = None
            self._fallback_replayed = False
            self._analyzer.set_active(False)
            if self._overlay is not None:
                self._overlay.hide()
            if self._desktop_visible:
                self._desktop.hide()
                self._desktop_visible = False

    def flush(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._fallback_show = None
        self._analyzer.close()
        if self._overlay is not None:
            self._overlay.close()
        self._desktop.flush(timeout=timeout)

    def _show_levels(self, levels: list[float]) -> None:
        if self._overlay is not None:
            self._overlay.show_levels(levels)

    def _show_overlay_or_desktop(
        self,
        state: str,
        timeout_ms: int,
        desktop_show: Callable[[], None],
        *,
        label: str | None = None,
    ) -> bool:
        self._fallback_show = desktop_show
        self._fallback_replayed = False
        if self._overlay is not None and self._overlay.show_state(
            state,
            timeout_ms=timeout_ms,
            label=label,
        ):
            if self._desktop_visible:
                self._desktop.hide()
                self._desktop_visible = False
            return True
        if not self._fallback_replayed:
            desktop_show()
        self._desktop_visible = True
        return False

    def _overlay_unavailable(self) -> None:
        """Replay the latest state if asynchronous overlay startup/I/O fails."""
        with self._state_lock:
            if self._closed or self._fallback_show is None or self._fallback_replayed:
                return
            self._analyzer.set_active(False)
            self._fallback_show()
            self._fallback_replayed = True
            self._desktop_visible = True


_OVERLAY_CSS = """
window {
  background-color: transparent;
}
.stenographer-hud {
  background-color: rgba(45, 45, 48, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.20);
  border-radius: 20px;
  padding: 12px 18px 14px 18px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.36);
}
.stenographer-status {
  color: #f2f2f2;
  font-family: "Caveat";
  font-size: 20px;
  font-weight: 600;
}
.stenographer-preview {
  color: rgba(242, 242, 242, 0.52);
  font-family: sans-serif;
  font-size: 12px;
}
.stenographer-version {
  color: rgba(242, 242, 242, 0.40);
  font-family: sans-serif;
  font-size: 11px;
}
"""


def _preview_markup(stable: str, provisional: str) -> str:
    """Return escaped Pango markup with a fainter revisable tail."""
    stable_escaped = html.escape(stable, quote=False)
    provisional_escaped = html.escape(provisional, quote=False)
    return (
        f'<span foreground="#f2f2f2" alpha="52%">{stable_escaped}</span>'
        f'<span foreground="#f2f2f2" alpha="28%">{provisional_escaped}</span>'
    )


def _prepare_spectrum_context(
    context: Any, width: int, height: int, *, clear_operator: Any
) -> None:
    """Clear stale pixels and clip spectrum painting to its drawing area."""
    context.save()
    context.set_operator(clear_operator)
    context.paint()
    context.restore()
    context.rectangle(0, 0, width, height)
    context.clip()


def _register_application_font(font_map: Any, path: str, family: str) -> bool:
    """Add a bundled font directly to Pango's active application font map."""
    try:
        if not font_map.add_font_file(path):
            return False
        font_map.changed()
        return font_map.get_family(family) is not None
    except AttributeError, OSError, TypeError:
        return False


def run_overlay_process() -> int:
    """Run the stdin-driven GTK helper. Used only by the private child mode."""
    try:
        import cairo
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell, Pango, PangoCairo
    except (ImportError, ValueError, AttributeError) as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1

    class OverlayApplication:
        def __init__(self) -> None:
            self.app = Gtk.Application(
                application_id="io.github.Harrison-Blair.stenographer.overlay",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.app.connect("activate", self._activate)
            self.window: Any | None = None
            self.status: Any | None = None
            self.preview: Any | None = None
            self.icon: Any | None = None
            self.drawing: Any | None = None
            self.levels = [0.0] * 16
            self.hide_generation = 0

        def _activate(self, app: Any) -> None:
            font_path = os.environ.get("STENOGRAPHER_FONT_PATH")
            if font_path:
                font_map = PangoCairo.FontMap.get_default()
                if _register_application_font(font_map, font_path, "Caveat"):
                    print("stenographer overlay: Caveat font ready", file=sys.stderr, flush=True)
                else:
                    print(f"WARNING: could not load font: {font_path}", file=sys.stderr)
            provider = Gtk.CssProvider()
            provider.load_from_data(_OVERLAY_CSS)
            display = Gdk.Display.get_default()
            if display is None:
                print("ERROR: no Wayland display", flush=True)
                app.quit()
                return
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

            self.window = Gtk.ApplicationWindow(application=app)
            self.window.set_decorated(False)
            self.window.set_resizable(False)
            Gtk4LayerShell.init_for_window(self.window)
            if not Gtk4LayerShell.is_layer_window(self.window):
                print("ERROR: could not initialize a layer-shell surface", flush=True)
                app.quit()
                return
            Gtk4LayerShell.set_namespace(self.window, "stenographer-spectrum")
            Gtk4LayerShell.set_layer(self.window, Gtk4LayerShell.Layer.OVERLAY)
            Gtk4LayerShell.set_keyboard_mode(
                self.window,
                Gtk4LayerShell.KeyboardMode.NONE,
            )
            Gtk4LayerShell.set_exclusive_zone(self.window, 0)
            Gtk4LayerShell.set_anchor(
                self.window,
                Gtk4LayerShell.Edge.BOTTOM,
                True,
            )

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            box.add_css_class("stenographer-hud")
            self.icon = Gtk.Image()
            self.icon.set_pixel_size(76)
            self.icon.set_visible(False)
            box.append(self.icon)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.status = Gtk.Label(label="Listening")
            self.status.set_xalign(0.0)
            self.status.set_hexpand(True)
            self.status.add_css_class("stenographer-status")
            header.append(self.status)

            version = Gtk.Label(label=f"v{__version__}")
            version.set_xalign(1.0)
            version.set_valign(Gtk.Align.START)
            version.add_css_class("stenographer-version")
            header.append(version)
            content.append(header)

            self.preview = Gtk.Label()
            self.preview.set_xalign(0.0)
            self.preview.set_width_chars(42)
            self.preview.set_max_width_chars(42)
            self.preview.set_ellipsize(Pango.EllipsizeMode.START)
            self.preview.set_single_line_mode(True)
            self.preview.set_hexpand(True)
            self.preview.add_css_class("stenographer-preview")
            content.append(self.preview)

            self.drawing = Gtk.DrawingArea()
            self.drawing.set_content_width(280)
            self.drawing.set_content_height(54)
            self.drawing.set_hexpand(True)
            self.drawing.set_draw_func(self._draw_spectrum)
            content.append(self.drawing)
            box.append(content)
            self.window.set_child(box)
            self.window.realize()
            surface = self.window.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
            self.window.set_visible(False)

            threading.Thread(target=self._read_commands, name="overlay-ipc", daemon=True).start()
            print("READY", flush=True)

        def _read_commands(self) -> None:
            for line in sys.stdin:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError, TypeError:
                    continue
                GLib.idle_add(self._handle_command, message)
            GLib.idle_add(self.app.quit)

        def _handle_command(self, message: dict[str, Any]) -> bool:
            command = message.get("command")
            if command == "quit":
                self.app.quit()
                return GLib.SOURCE_REMOVE
            if command == "configure":
                self.levels = [0.0] * int(message.get("band_count", 16))
                icon_path = str(message.get("icon_path", ""))
                if icon_path:
                    self.icon.set_from_file(icon_path)
                    self.icon.set_visible(True)
                Gtk4LayerShell.set_margin(
                    self.window,
                    Gtk4LayerShell.Edge.BOTTOM,
                    int(message.get("margin_bottom", 32)),
                )
                return GLib.SOURCE_REMOVE
            if command == "levels":
                incoming = message.get("levels")
                if isinstance(incoming, list):
                    self.levels = [float(np.clip(value, 0.0, 1.0)) for value in incoming]
                    self.drawing.queue_draw()
                return GLib.SOURCE_REMOVE
            if command == "preview":
                stable = message.get("stable", "")
                provisional = message.get("provisional", "")
                if isinstance(stable, str) and isinstance(provisional, str):
                    self.preview.set_markup(_preview_markup(stable, provisional))
                return GLib.SOURCE_REMOVE
            if command == "preview_clear":
                self.preview.set_label("")
                return GLib.SOURCE_REMOVE
            if command == "state":
                self._set_state(
                    str(message.get("state", "hidden")),
                    int(message.get("timeout_ms", 0)),
                    str(message["label"]) if isinstance(message.get("label"), str) else None,
                )
            return GLib.SOURCE_REMOVE

        def _set_state(self, state: str, timeout_ms: int, label: str | None = None) -> None:
            self.hide_generation += 1
            labels = {
                "ready": "Ready",
                "listening": "Listening",
                "loading": "Loading model · Listening",
                "transcribing": "Transcribing",
                "unloaded": "Speech model unloaded",
            }
            if state == "hidden":
                self.window.set_visible(False)
                return
            self.status.set_label(label or labels.get(state, state.replace("_", " ").title()))
            if state not in {"listening", "loading"}:
                self.levels = [0.0] * len(self.levels)
                self.drawing.queue_draw()
            self.window.present()
            if timeout_ms > 0:
                generation = self.hide_generation

                def hide_if_current() -> bool:
                    if generation == self.hide_generation:
                        self.window.set_visible(False)
                    return GLib.SOURCE_REMOVE

                GLib.timeout_add(timeout_ms, hide_if_current)

        def _draw_spectrum(self, _area: Any, context: Any, width: int, height: int) -> None:
            # Explicitly clear and clip every frame. Some GTK/Cairo compositor
            # combinations otherwise retain a stale antialiased edge pixel
            # after a tall bar shrinks, visible as a lone white HUD speck.
            _prepare_spectrum_context(
                context,
                width,
                height,
                clear_operator=cairo.Operator.CLEAR,
            )
            count = max(1, len(self.levels))
            gap = 5.0
            baseline = max(2.0, height - 8.0)
            bar_width = max(3.0, (width - gap * (count - 1)) / count)
            for index, level in enumerate(self.levels):
                x = index * (bar_width + gap)
                fill_height = max(2.0, float(level) * baseline)
                context.set_source_rgba(1.0, 1.0, 1.0, 0.68)
                context.rectangle(x, baseline - fill_height, bar_width, fill_height)
                context.fill()

        def run(self) -> int:
            return int(self.app.run([]))

    try:
        return OverlayApplication().run()
    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        raise SystemExit(run_overlay_process())
    raise SystemExit("stenographer.visualizer is an internal module")
