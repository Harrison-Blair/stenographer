# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure conversion of focused Qt key metadata to physical binding names."""

import pytest

from stenographer.platform.linux import LinuxPlatform


@pytest.mark.parametrize(
    ("key", "virtual", "scan", "expected"),
    [
        (ord("Z"), ord("z"), 29, "KEY_Y"),  # German Z on physical Y (21 + 8).
        (ord("!"), ord("!"), 10, "KEY_1"),  # Shift+1 (2 + 8).
        (0x01000020, 0, 62, "KEY_RIGHTSHIFT"),
        (0x01000021, 0, 105, "KEY_RIGHTCTRL"),
        (0x01000023, 0, 108, "KEY_RIGHTALT"),
        (0x01000022, 0, 134, "KEY_RIGHTMETA"),
    ],
)
def test_native_scan_code_takes_priority_over_layout(key, virtual, scan, expected):
    assert LinuxPlatform().focused_key_name(key, virtual, scan) == expected


@pytest.mark.parametrize("scan", [0, 7, 10000])
def test_missing_or_unmapped_scan_code_retains_fallbacks(scan):
    platform = LinuxPlatform()
    assert platform.focused_key_name(ord("Z"), ord("z"), scan) == "KEY_Z"
    assert platform.focused_key_name(0x01000021, 0xFFE4, scan) == "KEY_RIGHTCTRL"
    assert platform.focused_key_name(0x01000020, 0, scan) == "KEY_LEFTSHIFT"
    assert platform.focused_key_name(0x01000030, 0, scan) == "KEY_F1"
    assert platform.focused_key_name(-1, 0, scan) is None
