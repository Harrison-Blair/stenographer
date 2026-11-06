# SPDX-License-Identifier: GPL-3.0-or-later
"""Place the pill under the pointer from Hyprland's request socket."""

from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from stenographer.lib.logging.pipeline import log_failure

log = logging.getLogger(__name__)

POINTER_GAP = 32
_SOCKET_TIMEOUT_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class HyprlandMonitor:
    """One output in global logical coordinates, after scale and transform."""

    name: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class PointerPlacement:
    """Layer-surface margins from the top-left corner of one named output."""

    output_name: str
    margin_top: int
    margin_left: int


def place_under_pointer(
    pointer: tuple[int, int],
    monitors: tuple[HyprlandMonitor, ...],
    pill_bounds: tuple[int, int, int, int],
) -> PointerPlacement | None:
    """Center the pill below the pointer and slide it fully onto the monitor. PURE.

    ``pill_bounds`` are logical canvas coordinates. A margin is negative when
    the transparent canvas edge must pass the monitor edge so that the visible
    pill can touch it. No monitor under the pointer returns ``None``.
    """
    pointer_x, pointer_y = pointer
    monitor = next(
        (
            item
            for item in monitors
            if item.x <= pointer_x < item.x + item.width
            and item.y <= pointer_y < item.y + item.height
        ),
        None,
    )
    if monitor is None:
        return None
    pill_left, pill_top, pill_right, pill_bottom = pill_bounds
    pill_width = pill_right - pill_left
    pill_height = pill_bottom - pill_top
    visible_left = min(
        max(pointer_x - pill_width // 2, monitor.x),
        monitor.x + monitor.width - pill_width,
    )
    visible_top = min(pointer_y + POINTER_GAP, monitor.y + monitor.height - pill_height)
    return PointerPlacement(
        output_name=monitor.name,
        margin_top=visible_top - monitor.y - pill_top,
        margin_left=visible_left - monitor.x - pill_left,
    )


def _whole_number(obj: dict[str, object], key: str) -> int:
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Hyprland field {key} is not a whole number")
    return value


def parse_cursor(reply: bytes) -> tuple[int, int]:
    """Read a ``j/cursorpos`` reply; malformed data raises ``ValueError``."""
    obj = json.loads(reply)
    if not isinstance(obj, dict):
        raise ValueError("Hyprland cursor reply is not an object")
    try:
        return _whole_number(obj, "x"), _whole_number(obj, "y")
    except KeyError as exc:
        raise ValueError(f"Hyprland cursor reply has no field {exc}") from None


def _parse_monitor(obj: object) -> HyprlandMonitor:
    if not isinstance(obj, dict):
        raise ValueError("Hyprland monitor is not an object")
    try:
        name = obj["name"]
        scale = obj["scale"]
        mode_width = _whole_number(obj, "width")
        mode_height = _whole_number(obj, "height")
        transform = _whole_number(obj, "transform")
        x = _whole_number(obj, "x")
        y = _whole_number(obj, "y")
    except KeyError as exc:
        raise ValueError(f"Hyprland monitor has no field {exc}") from None
    if not isinstance(name, str):
        raise ValueError("Hyprland monitor name is not text")
    if isinstance(scale, bool) or not isinstance(scale, int | float) or scale <= 0:
        raise ValueError("Hyprland monitor scale is not a positive number")
    if transform % 2:
        # wl_output transforms 1, 3, 5, and 7 turn the mode by 90 degrees.
        mode_width, mode_height = mode_height, mode_width
    # The reply rounds the scale (1.3333334 for 4/3), so the division can fall just
    # below the true whole size.
    return HyprlandMonitor(name, x, y, round(mode_width / scale), round(mode_height / scale))


def parse_monitors(reply: bytes) -> tuple[HyprlandMonitor, ...]:
    """Read a ``j/monitors`` reply; malformed data raises ``ValueError``."""
    obj = json.loads(reply)
    if not isinstance(obj, list):
        raise ValueError("Hyprland monitors reply is not a list")
    return tuple(_parse_monitor(item) for item in obj)


def _request(path: Path, command: bytes) -> bytes:
    """Send one request; Hyprland closes the connection after its reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
        connection.connect(str(path))
        connection.sendall(command)
        chunks = []
        while chunk := connection.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def query_pointer_placement(pill_bounds: tuple[int, int, int, int]) -> PointerPlacement | None:
    """Return the placement for this show, or ``None`` to use bottom center.

    Outside Hyprland the variables are absent, which is no failure and has no
    log line. A failed query has a log line. The helper is the only caller, and
    the socket timeout limits how long a stuck compositor can delay it.
    """
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not signature or not runtime_dir:
        return None
    path = Path(runtime_dir) / "hypr" / signature / ".socket.sock"
    try:
        pointer = parse_cursor(_request(path, b"j/cursorpos"))
        monitors = parse_monitors(_request(path, b"j/monitors"))
    except (OSError, ValueError) as exc:
        log_failure(log, logging.WARNING, "overlay_helper: hyprland_query_failed", exc, safe=True)
        return None
    return place_under_pointer(pointer, monitors, pill_bounds)
