# SPDX-License-Identifier: GPL-3.0-or-later
"""The clipboard backend decision: pure pick_backend(), plus the REAL probes.

The copy round trips (wl-copy and xclip) are covered by the integration smoke
suite in tests/delivery/test_deliver_smoke.py — nothing here mocks subprocess,
and nothing here writes to the clipboard. ``detect_clipboard_backend`` and
``probe_clipboard`` are read-only, so they are run against this session for
real and asserted against whichever environment is present.
"""

from __future__ import annotations

import logging
import os
import shutil

from stenographer.lib.platform.linux.clipboard import (
    _wayland_global_interfaces,
    copy_both_selections,
    copy_both_selections_x11,
    copy_for_backend,
    detect_clipboard_backend,
    pick_backend,
    probe_clipboard,
)
from stenographer.lib.platform.linux.clipboard_backend import ClipboardBackend

_CLIPBOARD_LOGGER = "stenographer.lib.platform.linux.clipboard"


def test_pick_backend_prefers_wl_copy_with_ext_data_control():
    globals_seen = {"wl_compositor", "ext_data_control_manager_v1"}
    assert pick_backend(globals_seen, have_display=True) is ClipboardBackend.WL_COPY


def test_pick_backend_prefers_wl_copy_with_zwlr_data_control():
    globals_seen = {"wl_compositor", "zwlr_data_control_manager_v1"}
    assert pick_backend(globals_seen, have_display=False) is ClipboardBackend.WL_COPY


def test_pick_backend_x11_when_no_data_control_and_display_present():
    # GNOME <= 46: no data-control global; XWayland available.
    globals_seen = {"wl_compositor", "wl_shm", "xdg_wm_base"}
    assert pick_backend(globals_seen, have_display=True) is ClipboardBackend.X11


def test_pick_backend_x11_when_wayland_probe_fails_and_display_present():
    assert pick_backend(None, have_display=True) is ClipboardBackend.X11


def test_pick_backend_keeps_wl_copy_when_wayland_probe_fails_without_alternative():
    assert pick_backend(None, have_display=False) is ClipboardBackend.WL_COPY


def test_pick_backend_keeps_wl_copy_without_any_alternative():
    # No data-control AND no X display: stay on wl-copy (status quo; its
    # failure is already the safe no-chord path).
    assert pick_backend(set(), have_display=False) is ClipboardBackend.WL_COPY


def test_copy_for_backend_maps_each_backend_to_its_copier():
    assert copy_for_backend(ClipboardBackend.WL_COPY) is copy_both_selections
    assert copy_for_backend(ClipboardBackend.X11) is copy_both_selections_x11


def test_backend_detection_runs_the_real_compositor_probe(caplog):
    """One registry roundtrip against whatever session this host is running.

    Both outcomes are real and both are asserted: a reachable compositor must
    decide from the globals it advertises, and an unreachable one must fall
    back exactly as ``pick_backend`` does for an unavailable probe — and say so
    at WARNING, because that log line is why delivery is on the backend it is.
    """
    have_display = bool(os.environ.get("DISPLAY"))
    with caplog.at_level(logging.WARNING, logger=_CLIPBOARD_LOGGER):
        backend = detect_clipboard_backend()
    assert isinstance(backend, ClipboardBackend)

    failures = [r for r in caplog.records if "wayland_probe_failed" in r.message]
    if failures:
        assert backend is pick_backend(None, have_display=have_display)
        assert f"backend={backend.value}" in failures[0].message
    else:
        interfaces = _wayland_global_interfaces()
        assert "wl_compositor" in interfaces
        assert backend is pick_backend(interfaces, have_display=have_display)


def test_clipboard_probe_reports_unavailable_when_no_copy_binary_is_installed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path))
    available, backend_name = probe_clipboard()
    assert available is False
    # Even with nothing installed, doctor is told which backend would be used.
    assert backend_name in {backend.value for backend in ClipboardBackend}


def test_clipboard_probe_finds_the_binary_the_detected_backend_needs(tmp_path, monkeypatch):
    for name in ("wl-copy", "xclip"):
        stub = tmp_path / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    available, backend_name = probe_clipboard()
    assert available is True
    backend = ClipboardBackend(backend_name)
    assert shutil.which("xclip" if backend is ClipboardBackend.X11 else "wl-copy") is not None
