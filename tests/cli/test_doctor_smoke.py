# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke for `doctor`: real probe, real exit code, nothing mocked.

Runs the actual capability probe against this machine and asserts the CLI
exit code agrees with the probe's own decision — 0 when everything required
is present, 78 otherwise (the exit-78 contract).
"""

from __future__ import annotations

import pytest

from stenographer.cli import doctor, main
from stenographer.config import Config

pytestmark = pytest.mark.integration


def test_probe_returns_real_capabilities():
    caps = doctor.probe(Config.defaults())
    assert isinstance(caps, doctor.Capabilities)
    assert caps.clipboard_backend in ("wl-copy", "x11")
    assert caps.audio_player in ("canberra-gtk-play", "pw-play", "paplay", None)
    assert caps.service_enabled is None or isinstance(caps.service_enabled, str)
    assert caps.service_active is None or isinstance(caps.service_active, str)
    assert isinstance(caps.overlay, doctor.OverlayCapability)
    assert doctor.format_overlay_status(caps.overlay) in {
        "disabled",
        "layer-shell",
        "XWayland fallback",
        "unavailable — no X display; set DISPLAY or enable XWayland",
        "unavailable — cannot connect to XWayland; check DISPLAY and session access",
        "unavailable — XWayland has no usable 32-bit ARGB visual",
        "unavailable — XWayland requires the Shape and RandR extensions",
        "unavailable — no usable layer-shell or XWayland backend; check the graphical session",
    }


def test_doctor_exit_code_matches_probe(capsys):
    caps = doctor.probe(Config.defaults())
    expected = 78 if doctor.missing_required(caps) else 0
    assert main(["doctor"]) == expected
    out = capsys.readouterr().out
    assert "capabilities" in out
