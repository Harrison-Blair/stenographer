# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK4 layer-shell helper process run in the private child mode."""

from __future__ import annotations

import html
import json
import os
import sys
import threading
from typing import Any

import numpy as np

from stenographer._version import __version__
from stenographer.visualizer.protocol import _HUD_STATE_LABELS

_PREVIEW_WIDTH_CHARS = 42
_PREVIEW_ROWS = 2
_PREVIEW_RECENT_CHARS = 96
_PREVIEW_HEIGHT_PX = 34

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
    """Return recent, escaped Pango markup with a fainter revisable tail."""
    stable, provisional = _trim_preview(stable, provisional)
    stable_escaped = html.escape(stable, quote=False)
    provisional_escaped = html.escape(provisional, quote=False)
    return (
        f'<span foreground="#f7f7f7" alpha="92%">{stable_escaped}</span>'
        f'<span foreground="#f2f2f2" alpha="58%" style="italic">'
        f"{provisional_escaped}</span>"
    )


def _trim_preview(
    stable: str,
    provisional: str,
    limit: int = _PREVIEW_RECENT_CHARS,
) -> tuple[str, str]:
    """Keep the newest preview text and preserve its stable/tail boundary."""
    combined = stable + provisional
    if len(combined) <= limit:
        return stable, provisional
    target = len(combined) - limit
    boundary = next(
        (index + 1 for index in range(target, len(combined)) if combined[index].isspace()),
        target,
    )
    if boundary < len(stable):
        return "…" + stable[boundary:], provisional
    return "", "…" + provisional[max(0, boundary - len(stable)) :]


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
            if not self._install_styles(app):
                return
            if not self._configure_layer_shell(app):
                return
            self._build_widgets()
            self._start_ipc_thread()

        def _install_styles(self, app: Any) -> bool:
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
                return False
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            return True

        def _configure_layer_shell(self, app: Any) -> bool:
            self.window = Gtk.ApplicationWindow(application=app)
            self.window.set_decorated(False)
            self.window.set_resizable(False)
            Gtk4LayerShell.init_for_window(self.window)
            if not Gtk4LayerShell.is_layer_window(self.window):
                print("ERROR: could not initialize a layer-shell surface", flush=True)
                app.quit()
                return False
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
            return True

        def _build_widgets(self) -> None:
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
            self.preview.set_width_chars(_PREVIEW_WIDTH_CHARS)
            self.preview.set_max_width_chars(_PREVIEW_WIDTH_CHARS)
            self.preview.set_lines(_PREVIEW_ROWS)
            self.preview.set_wrap(True)
            self.preview.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.preview.set_ellipsize(Pango.EllipsizeMode.END)
            self.preview.set_single_line_mode(False)
            self.preview.set_height_request(_PREVIEW_HEIGHT_PX)
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

        def _start_ipc_thread(self) -> None:
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
            if state == "hidden":
                self.window.set_visible(False)
                return
            self.status.set_label(
                label or _HUD_STATE_LABELS.get(state, state.replace("_", " ").title())
            )
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
