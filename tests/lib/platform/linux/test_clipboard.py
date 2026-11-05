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

import pytest

from stenographer.lib.platform.linux.clipboard import (
    ClipboardBackend,
    _wayland_global_interfaces,
    detect_clipboard_backend,
    pick_backend,
    probe_clipboard,
)

_CLIPBOARD_LOGGER = "stenographer.lib.platform.linux.clipboard"


@pytest.mark.parametrize(
    ("globals_seen", "have_display", "expected"),
    [
        pytest.param(
            {"wl_compositor", "ext_data_control_manager_v1"},
            True,
            ClipboardBackend.WL_COPY,
            id="ext_data_control",
        ),
        pytest.param(
            {"wl_compositor", "zwlr_data_control_manager_v1"},
            False,
            ClipboardBackend.WL_COPY,
            id="zwlr_data_control",
        ),
        pytest.param(
            {"wl_compositor", "wl_shm", "xdg_wm_base"},
            True,
            ClipboardBackend.X11,
            id="gnome_46_no_data_control_with_xwayland",
        ),
        pytest.param(None, True, ClipboardBackend.X11, id="probe_failed_with_display"),
        pytest.param(None, False, ClipboardBackend.WL_COPY, id="probe_failed_without_display"),
        # No data-control AND no X display: stay on wl-copy (status quo; its
        # failure is already the safe no-chord path).
        pytest.param(set(), False, ClipboardBackend.WL_COPY, id="no_alternative"),
    ],
)
def test_pick_backend(globals_seen, have_display, expected):
    assert pick_backend(globals_seen, have_display=have_display) is expected


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
    available, read_available, backend_name = probe_clipboard()
    assert available is False
    assert read_available is False
    # Even with nothing installed, doctor is told which backend would be used.
    assert backend_name in {backend.value for backend in ClipboardBackend}


def test_clipboard_probe_finds_the_binary_the_detected_backend_needs(tmp_path, monkeypatch):
    for name in ("wl-copy", "xclip"):
        stub = tmp_path / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    available, _read_available, backend_name = probe_clipboard()
    assert available is True
    backend = ClipboardBackend(backend_name)
    assert shutil.which("xclip" if backend is ClipboardBackend.X11 else "wl-copy") is not None
