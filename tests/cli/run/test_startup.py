# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-gated startup policy."""

from __future__ import annotations

import dataclasses

from stenographer.cli.run.startup import startup_clipboard_backend
from stenographer.lib.diagnostics.capabilities import REQUIRED
from stenographer.overlay.capabilities.models import OverlayCapability
from tests.cli.support import capabilities


def _startup_caps(**overrides):
    return capabilities(**({"overlay": OverlayCapability.disabled()} | overrides))


def test_startup_gate_tracks_every_current_doctor_requirement():
    assert startup_clipboard_backend(_startup_caps()) == "wl-copy"
    for name in REQUIRED:
        caps = dataclasses.replace(_startup_caps(), **{name: False})
        assert startup_clipboard_backend(caps) is None, name


def test_startup_gate_ignores_optional_capabilities_and_reuses_backend():
    caps = _startup_caps(
        clipboard_backend="x11",
        cue_player=None,
        service_enabled=None,
        service_active=None,
        overlay=OverlayCapability.disabled(),
    )
    assert startup_clipboard_backend(caps) == "x11"
