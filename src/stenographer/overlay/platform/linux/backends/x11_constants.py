# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import re

from Xlib.protocol import rq

log = logging.getLogger(__name__)


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
