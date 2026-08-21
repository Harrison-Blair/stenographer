# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke suite for delivery (spec §6.3, M4 Verify).

Real, non-mocked boundaries: genuine backend detection against the session
compositor, a real copy → read-back round trip on BOTH selections through the
backend that detection selected, and a real uinput virtual keyboard emitting
the paste chord. Nothing is mocked — the clipboard and the /dev/uinput device
are the actual OS resources the daemon uses.

On a data-control compositor (wlroots, GNOME >= 47) this exercises the wl-copy
path; on GNOME <= 46 it exercises the xclip/XWayland path — the same choice the
daemon makes at startup.

Manual per-compositor step (the paste half of the M4 Verify clause, which cannot
be asserted programmatically without a focused window under test):

    Run this with a terminal focused, once on a Hyprland session and once on a
    GNOME Wayland session. After the chord fires, confirm the unique string was
    pasted at the cursor in the focused terminal on EACH compositor.

Self-skips unless STENOGRAPHER_INTEGRATION=1, the selected backend's binaries
are on PATH, and a uinput device can actually be opened (writable /dev/uinput),
so the default unit run never touches the clipboard or creates an input device.
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

from stenographer.childenv import child_env  # noqa: E402
from stenographer.deliver import (  # noqa: E402
    ClipboardBackend,
    Deliverer,
    UinputKeyboard,
    copy_for_backend,
    detect_clipboard_backend,
)

BACKEND = detect_clipboard_backend()

if BACKEND is ClipboardBackend.X11:
    if shutil.which("xclip") is None:
        pytest.skip("detected x11 clipboard backend but xclip not on PATH", allow_module_level=True)
elif shutil.which("wl-copy") is None or shutil.which("wl-paste") is None:
    pytest.skip("wl-copy/wl-paste not on PATH", allow_module_level=True)

_COPY = copy_for_backend(BACKEND)


def _open_keyboard() -> UinputKeyboard:
    """Open a real uinput device, skipping if /dev/uinput is not writable."""
    kb = UinputKeyboard()
    try:
        kb.send_chord()  # forces lazy device creation
    except (PermissionError, FileNotFoundError) as exc:
        pytest.skip(f"/dev/uinput not usable: {exc}")
    return kb


def _paste(*, primary: bool = False) -> str:
    """Read a selection back through the SELECTED backend's reader."""
    if BACKEND is ClipboardBackend.X11:
        argv = ["xclip", "-selection", "primary" if primary else "clipboard", "-o"]
    else:
        argv = ["wl-paste", "-n", *(["--primary"] if primary else [])]
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        timeout=10.0,
        env=child_env(),
    ).stdout.decode("utf-8")


def test_detection_returns_a_backend_on_the_real_session():
    assert BACKEND in (ClipboardBackend.WL_COPY, ClipboardBackend.X11)


def test_copy_round_trips_both_selections_via_selected_backend():
    token = f"stenographer-smoke-{uuid.uuid4()}"
    assert _COPY(token) is True
    # The Verify clause: clipboard readable back, on BOTH selections.
    assert _paste() == token
    assert _paste(primary=True) == token


def test_deliverer_delivers_and_reports_true():
    token = f"stenographer-smoke-{uuid.uuid4()}"
    kb = _open_keyboard()
    try:
        deliverer = Deliverer(keyboard=kb, copy=_COPY)
        # Real copy + real chord emit; returns True and never raises.
        assert deliverer.deliver(token) is True
        assert _paste() == token
    finally:
        kb.close()
