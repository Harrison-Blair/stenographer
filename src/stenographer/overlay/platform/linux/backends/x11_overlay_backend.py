# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import logging
import os
import time

from Xlib import X, Xatom, Xutil
from Xlib import display as xdisplay
from Xlib.ext import randr, shape

from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.overlay.platform.linux.backends.errors import BackendUnavailableError
from stenographer.overlay.platform.linux.backends.helper_backend import HelperBackend
from stenographer.overlay.platform.linux.backends.monitor import Monitor
from stenographer.overlay.platform.linux.backends.pict_format import PictFormat
from stenographer.overlay.platform.linux.backends.placement import Placement
from stenographer.overlay.platform.linux.backends.stacking_reassert_plan import StackingReassertPlan
from stenographer.overlay.platform.linux.backends.x11 import (
    _render_formats,
    _valid_monitor,
    choose_dpi_scale,
    consume_stacking_reassert,
    freeze_placement,
    parse_xft_dpi,
    placement_output_vanished,
    plan_upload_chunks,
    select_argb_visual,
    select_monitor,
    stacking_reassert_timeout,
    start_stacking_reassert,
)
from stenographer.overlay.platform.linux.backends.x11_constants import (
    _ARGB_DEPTH,
    _BYTES_PER_PIXEL,
    log,
)
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason
from stenographer.overlay.rendering.frame import OverlayFrame
from stenographer.overlay.rendering.render import overlay_position, premultiplied_argb32


class X11OverlayBackend(HelperBackend):
    """Override-redirect, non-input XWayland lifecycle pill."""

    backend = Backend.XWAYLAND

    def __init__(self) -> None:
        super().__init__()
        self._display = None
        self._screen = None
        self._visual = None
        self._pict_format: PictFormat | None = None
        self._window = None
        self._gc = None
        self._colormap = None
        self._placement: Placement | None = None
        self._compositor_translation = (0, 0)
        self._target_position: tuple[int, int] | None = None
        self._requested_position: tuple[int, int] | None = None
        self._window_epoch = 0
        self._stacking_reassert: StackingReassertPlan | None = None

        if not os.environ.get("DISPLAY"):
            raise BackendUnavailableError(UnavailableReason.NO_X_DISPLAY)
        try:
            self._display = xdisplay.Display()
        except Exception as exc:
            # ``from None`` on the wire: the parent gets the fixed reason only.
            log_failure(log, logging.INFO, "overlay_helper: x_connect_failed", exc, safe=True)
            raise BackendUnavailableError(UnavailableReason.X_CONNECT_FAILED) from None
        try:
            missing = tuple(
                name
                for name in (shape.extname, randr.extname)
                if not self._display.has_extension(name)
            )
            if missing:
                log.info(
                    fmt_event("overlay_helper", "x_extensions_missing", missing="|".join(missing))
                )
                raise BackendUnavailableError(UnavailableReason.X_EXTENSIONS_UNAVAILABLE)
            self._screen = self._display.screen()
            render_formats = _render_formats(self._display)
            visuals = (
                visual
                for depth in self._screen.allowed_depths
                if depth.depth == _ARGB_DEPTH
                for visual in depth.visuals
            )
            selected = (
                None if render_formats is None else select_argb_visual(visuals, *render_formats)
            )
            if selected is None:
                raise BackendUnavailableError(UnavailableReason.X_ARGB_UNAVAILABLE)
            self._visual, self._pict_format = selected
            # Select only output topology changes.  Pointer/key/button events
            # are intentionally never selected by this click-through helper.
            self._screen.root.xrandr_select_input(
                randr.RRScreenChangeNotifyMask
                | randr.RRCrtcChangeNotifyMask
                | randr.RROutputChangeNotifyMask
            )
            self._display.sync()
        except BackendUnavailableError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            log_failure(log, logging.INFO, "overlay_helper: x_setup_failed", exc, safe=True)
            raise BackendUnavailableError(UnavailableReason.X_EXTENSIONS_UNAVAILABLE) from None

    def _root_monitor(self) -> Monitor:
        assert self._screen is not None
        return Monitor(
            None,
            0,
            0,
            self._screen.width_in_pixels,
            self._screen.height_in_pixels,
            millimeter_width=self._screen.width_in_mms,
        )

    def _monitors(self) -> tuple[Monitor, ...]:
        assert self._display is not None and self._screen is not None
        root = self._screen.root
        resources = root.xrandr_get_screen_resources_current()
        primary = root.xrandr_get_output_primary().output
        monitors = []
        for output in resources.outputs:
            info = self._display.xrandr_get_output_info(output, resources.config_timestamp)
            connected = info.connection == randr.Connected and bool(info.crtc)
            if not connected:
                monitors.append(Monitor(output, 0, 0, 0, 0, connected=False))
                continue
            crtc = self._display.xrandr_get_crtc_info(info.crtc, resources.config_timestamp)
            monitors.append(
                Monitor(
                    output,
                    crtc.x,
                    crtc.y,
                    crtc.width,
                    crtc.height,
                    primary=output == primary,
                    connected=True,
                    millimeter_width=info.mm_width,
                )
            )
        return tuple(monitors)

    def _choose_monitor(self) -> Monitor:
        assert self._screen is not None
        pointer = self._screen.root.query_pointer()
        root = self._root_monitor()
        return select_monitor(
            self._monitors(),
            pointer=(pointer.root_x, pointer.root_y),
            root_rect=root.rect,
        )

    def _xft_dpi(self) -> float | None:
        assert self._display is not None and self._screen is not None
        resource_manager = self._display.intern_atom("RESOURCE_MANAGER")
        value = self._screen.root.get_full_property(resource_manager, Xatom.STRING)
        return parse_xft_dpi(None if value is None else value.value)

    def _scale_for(self, monitor: Monitor) -> float:
        return choose_dpi_scale(
            xft_dpi=self._xft_dpi(),
            pixel_width=monitor.width,
            millimeter_width=monitor.millimeter_width,
        )

    def _set_properties(self, window) -> None:
        assert self._display is not None
        atom = self._display.intern_atom
        window.change_property(
            atom("_NET_WM_WINDOW_TYPE"),
            Xatom.ATOM,
            32,
            [atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")],
        )
        self._set_stacking_properties(window)
        window.change_text_property(atom("_NET_WM_NAME"), atom("UTF8_STRING"), "Stenographer")
        window.set_wm_hints(flags=Xutil.InputHint, input=0)
        window.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])

    def _set_stacking_properties(self, window) -> None:
        assert self._display is not None
        atom = self._display.intern_atom
        window.change_property(
            atom("_NET_WM_STATE"),
            Xatom.ATOM,
            32,
            [
                atom("_NET_WM_STATE_ABOVE"),
                atom("_NET_WM_STATE_SKIP_TASKBAR"),
                atom("_NET_WM_STATE_SKIP_PAGER"),
            ],
        )

    def _draw(self) -> None:
        self._show(self._state)

    def _repaint(self) -> None:
        if self._window is not None:
            self._show(self._state)

    def _teardown(self) -> None:
        self._destroy_window()

    def _show(self, state: OverlayState, *, monitor: Monitor | None = None) -> None:
        assert self._display is not None and self._screen is not None and self._visual is not None
        if self._placement is None:
            monitor = monitor or self._choose_monitor()
            self._placement = freeze_placement(None, monitor, self._scale_for(monitor))
        placement = self._placement
        frame = self._frame(state, scale=placement.scale)
        x, y = overlay_position(placement.monitor.rect, frame)
        self._target_position = (x, y)
        requested_x = x - self._compositor_translation[0]
        requested_y = y - self._compositor_translation[1]
        self._requested_position = (requested_x, requested_y)

        created = self._window is None
        if created:
            self._window_epoch += 1
            self._colormap = self._screen.root.create_colormap(self._visual.visual_id, X.AllocNone)
            self._window = self._screen.root.create_window(
                requested_x,
                requested_y,
                frame.width,
                frame.height,
                0,
                _ARGB_DEPTH,
                X.InputOutput,
                self._visual.visual_id,
                background_pixel=0,
                border_pixel=0,
                colormap=self._colormap,
                override_redirect=1,
                event_mask=0,
            )
            self._gc = self._window.create_gc()
            self._set_properties(self._window)
        else:
            self._window.configure(
                x=requested_x,
                y=requested_y,
                width=frame.width,
                height=frame.height,
            )

        self._upload(frame)
        self._window.map()
        # Mutter/XWayland may normalize an override-redirect window's EWMH
        # state while mapping it.  Reassert the fixed notification hints after
        # map, then apply core stacking as the authoritative X-side operation.
        self._set_properties(self._window)
        self._window.configure(stack_mode=X.Above)
        if created:
            self._stacking_reassert = start_stacking_reassert(
                epoch=self._window_epoch, now=time.monotonic()
            )
        if self._pulse.active and self._pulse.next_frame_at is None:
            self._pulse.arm(time.monotonic())
        self._display.flush()

    def _upload(self, frame: OverlayFrame) -> None:
        assert self._display is not None and self._window is not None and self._gc is not None
        byteorder = "little" if self._display.display.info.image_byte_order == 0 else "big"
        pixels = premultiplied_argb32(frame.image, byteorder=byteorder)
        row_bytes = frame.width * _BYTES_PER_PIXEL
        max_request_bytes = self._display.display.info.max_request_length << 2
        for y, height in plan_upload_chunks(
            width=frame.width,
            height=frame.height,
            max_request_bytes=max_request_bytes,
        ):
            start = y * row_bytes
            end = (y + height) * row_bytes
            self._window.put_image(
                self._gc,
                0,
                y,
                frame.width,
                height,
                X.ZPixmap,
                _ARGB_DEPTH,
                0,
                pixels[start:end],
            )

    def _destroy_window(self) -> None:
        window, self._window = self._window, None
        gc, self._gc = self._gc, None
        colormap, self._colormap = self._colormap, None
        self._window_epoch += 1
        self._stacking_reassert = None
        if window is not None:
            with contextlib.suppress(Exception):
                window.unmap()
            with contextlib.suppress(Exception):
                window.destroy()
        if gc is not None:
            with contextlib.suppress(Exception):
                gc.free()
        if colormap is not None:
            with contextlib.suppress(Exception):
                colormap.free()
        self._placement = None
        self._target_position = None
        self._requested_position = None
        self._pulse.disarm_frames()
        if self._display is not None:
            with contextlib.suppress(Exception):
                self._display.flush()

    def _extra_timeouts(self, now: float) -> tuple[float | None, ...]:
        return (
            stacking_reassert_timeout(
                self._stacking_reassert,
                current_epoch=self._window_epoch,
                now=now,
            ),
        )

    def _on_extra_timers(self) -> None:
        due, self._stacking_reassert = consume_stacking_reassert(
            self._stacking_reassert,
            current_epoch=self._window_epoch,
            now=time.monotonic(),
        )
        if not due or self._window is None or self._display is None:
            return
        self._set_stacking_properties(self._window)
        self._window.configure(stack_mode=X.Above)
        if self._target_position is not None and self._requested_position is not None:
            # Some XWayland compositors translate override-redirect positions
            # after map when their native monitor layout has negative origins.
            # RandR exposes only a normalized root, so learn the settled delta
            # and compensate every later request without compositor-specific IPC.
            geometry = self._window.get_geometry()
            translation = (
                geometry.x - self._requested_position[0],
                geometry.y - self._requested_position[1],
            )
            self._compositor_translation = translation
            requested_position = (
                self._target_position[0] - translation[0],
                self._target_position[1] - translation[1],
            )
            if requested_position != self._requested_position:
                self._requested_position = requested_position
                self._window.configure(x=requested_position[0], y=requested_position[1])
        self._display.flush()

    def _display_fd(self) -> int:
        assert self._display is not None
        return self._display.fileno()

    def _on_display_readable(self, _mask: int) -> None:
        assert self._display is not None
        saw_event = False
        while self._display.pending_events():
            self._display.next_event()
            saw_event = True
        if not saw_event or self._window is None or self._placement is None:
            return
        connected_outputs = {
            monitor.output for monitor in self._monitors() if _valid_monitor(monitor)
        }
        if not placement_output_vanished(self._placement, connected_outputs):
            return
        state = self._state
        replacement = self._choose_monitor()
        self._destroy_window()
        if state is not OverlayState.HIDDEN:
            self._show(state, monitor=replacement)

    def _close(self) -> None:
        self._destroy_window()
        if self._display is not None:
            try:
                self._display.close()
            except Exception as exc:
                log_failure(log, logging.DEBUG, "overlay_helper: x_close_failed", exc, safe=True)
            self._display = None
