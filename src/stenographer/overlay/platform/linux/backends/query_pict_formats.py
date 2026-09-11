# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from Xlib.protocol import rq

from stenographer.overlay.platform.linux.backends.x11_constants import (
    _PICT_FORMAT,
    _RENDER_QUERY_PICT_FORMATS,
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
