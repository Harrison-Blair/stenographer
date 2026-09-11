# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
import struct

from Xlib import X

from stenographer.overlay.platform.linux.backends.monitor import Monitor
from stenographer.overlay.platform.linux.backends.pict_format import PictFormat
from stenographer.overlay.platform.linux.backends.placement import Placement
from stenographer.overlay.platform.linux.backends.query_pict_formats import _QueryPictFormats
from stenographer.overlay.platform.linux.backends.stacking_reassert_plan import StackingReassertPlan
from stenographer.overlay.platform.linux.backends.x11_constants import (
    _ARGB_DEPTH,
    _BYTES_PER_PIXEL,
    _DEFAULT_DPI,
    _MAX_SANE_DPI,
    _MIN_SANE_DPI,
    _PICT_TYPE_DIRECT,
    _POST_MAP_REASSERT_DELAYS,
    _PUT_IMAGE_OVERHEAD,
    _RENDER_EXTENSION,
    _XFT_DPI,
)


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
