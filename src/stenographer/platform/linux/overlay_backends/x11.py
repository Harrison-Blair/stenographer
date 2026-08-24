# SPDX-License-Identifier: GPL-3.0-or-later
"""XWayland fallback for the isolated lifecycle/spectrum overlay.

The backend supplies only X primitives to ``HelperBackend``: RandR monitor
inventory and DPI, an override-redirect ARGB window with an empty input shape,
chunked ZPixmap uploads, and the bounded post-map EWMH reassertions XWayland
needs.  Lifecycle policy, the selector loop, the loading-frame timer, and the
frame request are shared (see ``base.py``); the pure helpers at the top make
placement and parsing policy independently testable.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import struct
import time
from dataclasses import dataclass

from Xlib import X, Xatom, Xutil
from Xlib import display as xdisplay
from Xlib.ext import randr, shape
from Xlib.protocol import rq

from stenographer.overlay.render import OverlayFrame, overlay_position, premultiplied_argb32
from stenographer.platform.linux.overlay_backends.base import (
    BackendUnavailableError,
    HelperBackend,
)
from stenographer.status import Backend, OverlayState, UnavailableReason

_ARGB_DEPTH = 32
_BYTES_PER_PIXEL = 4
_PUT_IMAGE_OVERHEAD = 24
_DEFAULT_DPI = 96.0
_MIN_SANE_DPI = 72.0
_MAX_SANE_DPI = 384.0
_XFT_DPI = re.compile(r"(?m)^Xft\.dpi:[ \t]*([^\r\n]+)[ \t]*$")
_POST_MAP_REASSERT_DELAYS = (0.1, 0.75)
_RENDER_EXTENSION = "RENDER"
_RENDER_QUERY_PICT_FORMATS = 1
_PICT_TYPE_DIRECT = 1


_PICT_FORMAT = rq.Struct(
    rq.Card32("format_id"),
    rq.Card8("format_type"),
    rq.Card8("depth"),
    rq.Pad(2),
    rq.Card16("red"),
    rq.Card16("red_mask"),
    rq.Card16("green"),
    rq.Card16("green_mask"),
    rq.Card16("blue"),
    rq.Card16("blue_mask"),
    rq.Card16("alpha"),
    rq.Card16("alpha_mask"),
    rq.Card32("colormap"),
)


class _QueryPictFormats(rq.ReplyRequest):
    """Minimal RENDER QueryPictFormats request missing from python-xlib 0.33."""

    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(_RENDER_QUERY_PICT_FORMATS),
        rq.RequestLength(),
    )
    _reply = rq.Struct(
        rq.ReplyCode(),
        rq.Pad(1),
        rq.Card16("sequence_number"),
        rq.ReplyLength(),
        rq.LengthOf("formats", 4),
        rq.Card32("num_screens"),
        rq.Card32("num_depths"),
        rq.Card32("num_visuals"),
        rq.Card32("num_subpixel"),
        rq.Pad(4),
        rq.List("formats", _PICT_FORMAT),
        rq.Binary("screen_data", pad=0),
    )


@dataclass(frozen=True, slots=True)
class Monitor:
    """One connected RandR output, or the root fallback when output is None."""

    output: int | None
    x: int
    y: int
    width: int
    height: int
    primary: bool = False
    connected: bool = True
    millimeter_width: int = 0

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def contains(self, point: tuple[int, int]) -> bool:
        px, py = point
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height


@dataclass(frozen=True, slots=True)
class PictFormat:
    """The RENDER fields needed to prove a visual has an alpha channel."""

    format_id: int
    format_type: int
    depth: int
    alpha_shift: int
    alpha_mask: int


@dataclass(frozen=True, slots=True)
class Placement:
    """Monitor and scale frozen for one hidden-to-visible interval."""

    monitor: Monitor
    scale: float


@dataclass(frozen=True, slots=True)
class StackingReassertPlan:
    """Bounded delayed EWMH reassertions tied to one X window epoch."""

    epoch: int
    deadlines: tuple[float, ...]


def start_stacking_reassert(*, epoch: int, now: float) -> StackingReassertPlan:
    """Schedule fixed post-map writes without sleeping the helper loop."""
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise ValueError("window epoch must be a non-negative integer")
    if not math.isfinite(now):
        raise ValueError("reassertion clock must be finite")
    return StackingReassertPlan(
        epoch,
        tuple(now + delay for delay in _POST_MAP_REASSERT_DELAYS),
    )


def stacking_reassert_timeout(
    plan: StackingReassertPlan | None, *, current_epoch: int, now: float
) -> float | None:
    """Return the next selector timeout, ignoring a stale window plan."""
    if plan is None or plan.epoch != current_epoch or not plan.deadlines:
        return None
    return max(0.0, plan.deadlines[0] - now)


def consume_stacking_reassert(
    plan: StackingReassertPlan | None, *, current_epoch: int, now: float
) -> tuple[bool, StackingReassertPlan | None]:
    """Consume all due deadlines and request at most one write per loop turn."""
    if plan is None or plan.epoch != current_epoch:
        return False, None
    if not plan.deadlines or now < plan.deadlines[0]:
        return False, plan
    remaining = tuple(deadline for deadline in plan.deadlines if deadline > now)
    return True, (StackingReassertPlan(plan.epoch, remaining) if remaining else None)


def freeze_placement(current: Placement | None, monitor: Monitor, scale: float) -> Placement:
    """Retain utterance placement; use the candidate only for a new surface."""
    if current is not None:
        return current
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("placement scale must be finite and positive")
    return Placement(monitor, scale)


def _valid_monitor(monitor: Monitor) -> bool:
    return monitor.connected and monitor.width > 0 and monitor.height > 0


def placement_output_vanished(
    placement: Placement | None, connected_outputs: frozenset[int] | set[int]
) -> bool:
    """Return whether the frozen placement's output stopped existing. PURE.

    Ordinary topology and geometry updates must preserve placement for the
    whole visible utterance; only a vanished selected output permits a move.
    The root fallback (``output is None``) never vanishes.
    """
    if placement is None or placement.monitor.output is None:
        return False
    return placement.monitor.output not in connected_outputs


def select_monitor(
    monitors: tuple[Monitor, ...] | list[Monitor],
    *,
    pointer: tuple[int, int],
    root_rect: tuple[int, int, int, int],
) -> Monitor:
    """Choose pointer output, primary output, then the root screen.

    The chosen object can be retained for the whole visible utterance so a
    moving pointer never causes the pill to jump between outputs.
    """
    root_x, root_y, root_width, root_height = root_rect
    if root_width <= 0 or root_height <= 0:
        raise ValueError("root geometry must be positive")
    connected = tuple(monitor for monitor in monitors if _valid_monitor(monitor))
    under_pointer = tuple(monitor for monitor in connected if monitor.contains(pointer))
    if under_pointer:
        return next((monitor for monitor in under_pointer if monitor.primary), under_pointer[0])
    primary = next((monitor for monitor in connected if monitor.primary), None)
    if primary is not None:
        return primary
    return Monitor(None, root_x, root_y, root_width, root_height)


def parse_xft_dpi(resources: str | bytes | None) -> float | None:
    """Extract the exact ``Xft.dpi`` resource without accepting lookalike keys."""
    if resources is None:
        return None
    if isinstance(resources, bytes):
        resources = resources.decode("latin-1", errors="replace")
    if not isinstance(resources, str):
        raise TypeError("X resources must be text, bytes, or None")
    match = _XFT_DPI.search(resources)
    if match is None:
        return None
    try:
        dpi = float(match.group(1))
    except ValueError:
        return None
    return dpi if math.isfinite(dpi) else None


def choose_dpi_scale(*, xft_dpi: float | None, pixel_width: int, millimeter_width: int) -> float:
    """Use a sane Xft DPI hint, then sane physical DPI, then 96 DPI."""
    candidates = [xft_dpi]
    if pixel_width > 0 and millimeter_width > 0:
        candidates.append(pixel_width * 25.4 / millimeter_width)
    for candidate in candidates:
        if (
            candidate is not None
            and math.isfinite(candidate)
            and _MIN_SANE_DPI <= candidate <= _MAX_SANE_DPI
        ):
            return candidate / _DEFAULT_DPI
    return 1.0


def plan_upload_chunks(
    *,
    width: int,
    height: int,
    max_request_bytes: int,
    bytes_per_pixel: int = _BYTES_PER_PIXEL,
    request_overhead: int = _PUT_IMAGE_OVERHEAD,
) -> tuple[tuple[int, int], ...]:
    """Split a ZPixmap upload into whole-row requests below the server limit."""
    if min(width, height, max_request_bytes, bytes_per_pixel) <= 0 or request_overhead < 0:
        raise ValueError("upload dimensions and request limit must be positive")
    row_bytes = width * bytes_per_pixel
    rows_per_chunk = (max_request_bytes - request_overhead) // row_bytes
    if rows_per_chunk < 1:
        raise ValueError("X request limit is too small for one image row")
    chunks = []
    y = 0
    while y < height:
        chunk_height = min(rows_per_chunk, height - y)
        chunks.append((y, chunk_height))
        y += chunk_height
    return tuple(chunks)


def select_argb_visual(visuals, visual_formats: dict[int, int], formats: dict[int, PictFormat]):
    """Return a core TrueColor visual proven alpha-capable by X RENDER."""
    for visual in visuals:
        pict_format = formats.get(visual_formats.get(visual.visual_id, -1))
        if (
            visual.visual_class == X.TrueColor
            and visual.red_mask == 0xFF0000
            and visual.green_mask == 0x00FF00
            and visual.blue_mask == 0x0000FF
            and pict_format is not None
            and pict_format.format_type == _PICT_TYPE_DIRECT
            and pict_format.depth == _ARGB_DEPTH
            and pict_format.alpha_shift == 24
            and pict_format.alpha_mask == 0xFF
        ):
            return visual, pict_format
    return None


def parse_pict_format_screens(screen_data: bytes, num_screens: int) -> dict[int, int]:
    """Map visual id -> picture format id from the RENDER reply tail. PURE.

    After the fixed format array, QueryPictFormats nests screens -> depths ->
    (visual, format) pairs.  All fields are native byte order because the X
    connection uses the client's byte order.  A reply that ends early is a
    protocol violation, never a partial mapping.
    """
    data = memoryview(bytes(screen_data))
    offset = 0
    visual_formats: dict[int, int] = {}

    def unpack(layout: str):
        nonlocal offset
        size = struct.calcsize(layout)
        if offset + size > len(data):
            raise ValueError("truncated RENDER format inventory")
        values = struct.unpack_from(layout, data, offset)
        offset += size
        return values

    for _screen in range(num_screens):
        num_depths, _fallback = unpack("=LL")
        for _depth in range(num_depths):
            _depth_value, _pad, num_visuals, _pad2 = unpack("=BBHL")
            for _visual in range(num_visuals):
                visual_id, format_id = unpack("=LL")
                visual_formats[visual_id] = format_id
    return visual_formats


def _render_formats(display) -> tuple[dict[int, int], dict[int, PictFormat]] | None:
    extension = display.query_extension(_RENDER_EXTENSION)
    if not extension.present:
        return None
    reply = _QueryPictFormats(display=display.display, opcode=extension.major_opcode)
    formats = {
        item.format_id: PictFormat(
            item.format_id,
            item.format_type,
            item.depth,
            item.alpha,
            item.alpha_mask,
        )
        for item in reply.formats
    }
    return parse_pict_format_screens(reply.screen_data, reply.num_screens), formats


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
        self._window_epoch = 0
        self._stacking_reassert: StackingReassertPlan | None = None

        if not os.environ.get("DISPLAY"):
            raise BackendUnavailableError(UnavailableReason.NO_X_DISPLAY)
        try:
            self._display = xdisplay.Display()
        except Exception:
            raise BackendUnavailableError(UnavailableReason.X_CONNECT_FAILED) from None
        try:
            if not (
                self._display.has_extension(shape.extname)
                and self._display.has_extension(randr.extname)
            ):
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
        except Exception:
            self.close()
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

        created = self._window is None
        if created:
            self._window_epoch += 1
            self._colormap = self._screen.root.create_colormap(self._visual.visual_id, X.AllocNone)
            self._window = self._screen.root.create_window(
                x,
                y,
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
            self._window.configure(x=x, y=y, width=frame.width, height=frame.height)

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
            with contextlib.suppress(Exception):
                self._display.close()
            self._display = None


__all__ = [
    "Monitor",
    "PictFormat",
    "Placement",
    "StackingReassertPlan",
    "X11OverlayBackend",
    "choose_dpi_scale",
    "consume_stacking_reassert",
    "freeze_placement",
    "parse_pict_format_screens",
    "parse_xft_dpi",
    "placement_output_vanished",
    "plan_upload_chunks",
    "select_argb_visual",
    "select_monitor",
    "stacking_reassert_timeout",
    "start_stacking_reassert",
]
