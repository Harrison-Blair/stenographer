# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure checks on the desktop theme tokens, stylesheet and rail icons (no Qt)."""

import re
import xml.etree.ElementTree as ET

from stenographer.overlay.render import _PILL_COLOR
from stenographer_desktop.icons import ICONS, NAVIGATION, icon_svg
from stenographer_desktop.theme import TOKENS, stylesheet

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_stylesheet_only_uses_theme_tokens():
    found = {match.lower() for match in HEX.findall(stylesheet())}
    assert found
    assert found <= {colour.lower() for colour in TOKENS.colours()}


def test_stylesheet_braces_balanced():
    depth = 0
    opened = 0
    for char in stylesheet():
        if char == "{":
            depth += 1
            opened += 1
        elif char == "}":
            depth -= 1
        assert depth >= 0
    assert depth == 0
    assert opened > 0


def test_navigation_icons_are_stroke_svgs():
    assert NAVIGATION == ("Overview", "Analytics", "Settings", "Service", "Diagnostics")
    for name in NAVIGATION:
        assert "COLOUR" in ICONS[name]
        root = ET.fromstring(icon_svg(name, "#123456"))
        assert root.tag.endswith("svg")
        assert root.get("fill") == "none"
        assert root.get("stroke") == "#123456"
        for element in root.iter():
            assert element.get("fill") in (None, "none")


def test_icon_svg_substitutes_colour_and_size():
    svg = icon_svg("Overview", "#abcdef", size=40)
    assert "#abcdef" in svg
    assert "COLOUR" not in svg
    assert 'width="40"' in svg
    assert 'height="40"' in svg


def test_ground_is_the_pill_colour():
    assert TOKENS.ground.lower() == "#{:02x}{:02x}{:02x}".format(*_PILL_COLOR)
