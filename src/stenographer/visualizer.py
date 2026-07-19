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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

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
        self._closed = False
        self._smoothed = np.zeros(band_count, dtype=np.float32)
        self._worker = threading.Thread(
            target=self._run,
            name="spectrum-analyzer",
            daemon=True,
        )
        self._worker.start()

    def set_active(self, active: bool) -> None:
        if active:
            self._active.set()
            return
        self._active.clear()
        self._smoothed.fill(0.0)
        self._discard_pending()

    def submit(self, samples: np.ndarray, sample_rate: int) -> None:
        """Copy and enqueue a block without waiting for the analyzer."""
        if not self._active.is_set() or self._closed:
            return
        packet = (np.asarray(samples, dtype=np.float32).reshape(-1).copy(), sample_rate)
        try:
            self._queue.put_nowait(packet)
            return
        except queue.Full:
            pass
        self._discard_pending()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(packet)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._active.clear()
        self._discard_pending()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_STOP)
        self._worker.join(timeout=2.0)

    def _discard_pending(self) -> None:
        with contextlib.suppress(queue.Empty):
            self._queue.get_nowait()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
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
            try:
                self._on_levels(self._smoothed.tolist())
            except Exception as exc:
                logger.debug("visualizer: level consumer failed: %s", exc)


class LayerShellOverlay:
    """JSON-lines controller for the GTK4 layer-shell helper process."""

    def __init__(
        self,
        cfg: VisualizerConfig,
        *,
        icon_path: pathlib.Path | None = None,
        font_path: pathlib.Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._icon_path = icon_path
        self._font_path = font_path
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._unavailable = False

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

    def show_state(self, state: str, *, timeout_ms: int = 0) -> bool:
        return self._send(
            {
                "command": "state",
                "state": state,
                "timeout_ms": timeout_ms,
            }
        )

    def show_levels(self, levels: list[float]) -> None:
        self._send({"command": "levels", "levels": levels})

    def hide(self) -> bool:
        if self._process is None:
            return False
        return self._send({"command": "state", "state": "hidden", "timeout_ms": 0})

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            try:
                if process.stdin is not None:
                    process.stdin.write('{"command":"quit"}\n')
                    process.stdin.flush()
                    process.stdin.close()
            except BrokenPipeError, OSError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def _send(self, message: dict[str, Any]) -> bool:
        with self._lock:
            if not self._ensure_started_locked():
                return False
            assert self._process is not None
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                self._process.stdin.flush()
                return True
            except (BrokenPipeError, OSError) as exc:
                logger.warning("visualizer: overlay pipe failed; using notifications: %s", exc)
                self._unavailable = True
                self._process = None
                return False

    def _ensure_started_locked(self) -> bool:
        if self._unavailable:
            return False
        if self._process is not None and self._process.poll() is None:
            return True
        if not self.probe():
            self._unavailable = True
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
            self._unavailable = True
            return False

        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_SECONDS)
        response = process.stdout.readline().strip() if readable else ""
        if response != "READY":
            logger.warning(
                "visualizer: GTK layer-shell unavailable; using notifications%s",
                f" ({response})" if response else "",
            )
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
            self._unavailable = True
            return False

        self._process = process
        setup = {
            "command": "configure",
            "margin_bottom": self._cfg.margin_bottom,
            "band_count": self._cfg.frequency_bands,
            "icon_path": str(self._icon_path) if self._icon_path is not None else "",
        }
        assert process.stdin is not None
        process.stdin.write(json.dumps(setup, separators=(",", ":")) + "\n")
        process.stdin.flush()
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
        self._overlay = (
            LayerShellOverlay(cfg, icon_path=icon_path, font_path=font_path)
            if cfg.enabled
            else None
        )
        self._desktop_visible = False
        self._closed = False
        self._analyzer = SpectrumAnalyzer(
            band_count=cfg.frequency_bands,
            min_frequency=cfg.min_frequency,
            max_frequency=cfg.max_frequency,
            on_levels=self._show_levels,
        )

    @staticmethod
    def overlay_probe() -> bool:
        return LayerShellOverlay.probe()

    def show_startup(self, binding: str) -> None:
        self._show_overlay_or_desktop(
            "ready",
            5000,
            lambda: self._desktop.show_startup(binding),
        )

    def show_listening(self) -> None:
        shown = self._show_overlay_or_desktop(
            "listening",
            0,
            self._desktop.show_listening,
        )
        self._analyzer.set_active(shown)

    def show_transcribing(self) -> None:
        self._analyzer.set_active(False)
        self._show_overlay_or_desktop(
            "transcribing",
            0,
            self._desktop.show_transcribing,
        )

    def show_model_loading(self) -> None:
        shown = self._show_overlay_or_desktop(
            "loading",
            0,
            self._desktop.show_model_loading,
        )
        self._analyzer.set_active(shown)

    def show_model_unloaded(self) -> None:
        self._analyzer.set_active(False)
        self._show_overlay_or_desktop(
            "unloaded",
            5000,
            self._desktop.show_model_unloaded,
        )

    def publish_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        self._analyzer.submit(samples, sample_rate)

    def hide(self) -> None:
        self._analyzer.set_active(False)
        if self._overlay is not None:
            self._overlay.hide()
        if self._desktop_visible:
            self._desktop.hide()
            self._desktop_visible = False

    def flush(self, timeout: float = 5.0) -> None:
        self._desktop.flush(timeout=timeout)
        if self._closed:
            return
        self._closed = True
        self._analyzer.close()
        if self._overlay is not None:
            self._overlay.close()

    def _show_levels(self, levels: list[float]) -> None:
        if self._overlay is not None:
            self._overlay.show_levels(levels)

    def _show_overlay_or_desktop(
        self,
        state: str,
        timeout_ms: int,
        desktop_show: Callable[[], None],
    ) -> bool:
        if self._overlay is not None and self._overlay.show_state(state, timeout_ms=timeout_ms):
            if self._desktop_visible:
                self._desktop.hide()
                self._desktop_visible = False
            return True
        desktop_show()
        self._desktop_visible = True
        return False


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
"""


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
        from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell, PangoCairo
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
            self.status = Gtk.Label(label="Listening")
            self.status.set_xalign(0.0)
            self.status.set_hexpand(True)
            self.status.add_css_class("stenographer-status")
            content.append(self.status)

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
            if command == "state":
                self._set_state(
                    str(message.get("state", "hidden")),
                    int(message.get("timeout_ms", 0)),
                )
            return GLib.SOURCE_REMOVE

        def _set_state(self, state: str, timeout_ms: int) -> None:
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
            self.status.set_label(labels.get(state, state.replace("_", " ").title()))
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
