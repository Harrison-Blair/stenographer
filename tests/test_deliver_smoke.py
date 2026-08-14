# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for delivery (spec §6.3, M4 Verify).

Real, non-mocked boundaries: a genuine wl-copy → wl-paste round trip on BOTH
Wayland selections, and a real uinput virtual keyboard emitting the paste chord.
Nothing is mocked — the clipboard and the /dev/uinput device are the actual OS
resources the daemon uses.

Manual per-compositor step (the paste half of the M4 Verify clause, which cannot
be asserted programmatically without a focused window under test):

    Run this with a terminal focused, once on a Hyprland session and once on a
    GNOME Wayland session. After the chord fires, confirm the unique string was
    pasted at the cursor in the focused terminal on EACH compositor.

Self-skips unless STENOGRAPHER_INTEGRATION=1, wl-copy/wl-paste are on PATH, and
a uinput device can actually be opened (writable /dev/uinput), so the default
unit run never touches the clipboard or creates an input device.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

if shutil.which("wl-copy") is None or shutil.which("wl-paste") is None:
    pytest.skip("wl-copy/wl-paste not on PATH", allow_module_level=True)

from stenographer.deliver import (  # noqa: E402
    Deliverer,
    UinputKeyboard,
    copy_both_selections,
)


def _open_keyboard() -> UinputKeyboard:
    """Open a real uinput device, skipping if /dev/uinput is not writable."""
    kb = UinputKeyboard()
    try:
        kb.send_chord()  # forces lazy device creation
    except (PermissionError, FileNotFoundError) as exc:
        pytest.skip(f"/dev/uinput not usable: {exc}")
    return kb


def _paste(*args: str) -> str:
    return subprocess.run(
        ["wl-paste", "-n", *args],
        check=True,
        capture_output=True,
        timeout=10.0,
    ).stdout.decode("utf-8")


def test_copy_both_selections_round_trips_via_wl_paste():
    token = f"stenographer-smoke-{uuid.uuid4()}"
    assert copy_both_selections(token) is True
    # The Verify clause: clipboard readable via wl-paste, on BOTH selections.
    assert _paste() == token
    assert _paste("--primary") == token


def test_deliverer_delivers_and_reports_true():
    token = f"stenographer-smoke-{uuid.uuid4()}"
    kb = _open_keyboard()
    try:
        deliverer = Deliverer(keyboard=kb)
        # Real copy + real chord emit; returns True and never raises.
        assert deliverer.deliver(token) is True
        assert _paste() == token
    finally:
        kb.close()
