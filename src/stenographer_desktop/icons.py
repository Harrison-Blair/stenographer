# SPDX-License-Identifier: GPL-3.0-or-later
"""Rail icons as stroke-only SVG templates. Qt-free so the pure tests can read them."""

from __future__ import annotations

NAVIGATION = ("Overview", "Analytics", "Settings", "Service", "Diagnostics")

_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
    'viewBox="0 0 24 24" fill="none" stroke="COLOUR" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
)

# Every shape is a stroke on a 24-unit grid; the colour and size are literal
# placeholders replaced by icon_svg (str.format would trip on the viewBox).
ICONS: dict[str, str] = {
    "Overview": _OPEN + '<circle cx="12" cy="12" r="9"/><path d="M12 12 L16 8"/></svg>',
    "Analytics": _OPEN
    + '<line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="5"/>'
    '<line x1="18" y1="20" x2="18" y2="14"/><line x1="3" y1="20" x2="21" y2="20"/></svg>',
    "Settings": _OPEN + '<line x1="4" y1="8" x2="20" y2="8"/><circle cx="9" cy="8" r="2.5"/>'
    '<line x1="4" y1="16" x2="20" y2="16"/><circle cx="15" cy="16" r="2.5"/></svg>',
    "Service": _OPEN + '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/></svg>',
    "Diagnostics": _OPEN + '<polyline points="3 12 7 12 10 5 14 19 17 12 21 12"/></svg>',
}


def icon_svg(name: str, colour: str, size: int = 20) -> str:
    """Render the named rail icon at *size* px in *colour*."""
    return ICONS[name].replace("COLOUR", colour).replace("{size}", str(size))
