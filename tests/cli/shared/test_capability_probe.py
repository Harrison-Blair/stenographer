# SPDX-License-Identifier: GPL-3.0-or-later
"""Composition of the required-capability probe with the optional overlay probe."""

from __future__ import annotations

from stenographer.cli.shared import capability_probe
from stenographer.lib.config.models import Config
from stenographer.lib.diagnostics.capability_result import Capabilities as CoreCapabilities
from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.protocol.backend import Backend


def test_probe_copies_every_core_field_and_appends_the_overlay_result(monkeypatch):
    core = CoreCapabilities(
        key_injector_ok=True,
        hotkey_access_ok=False,
        has_mic=True,
        model_cached=False,
        clipboard_ok=True,
        clipboard_backend="wl-copy",
        cue_player="pulse",
        service_enabled="enabled",
        service_active="active",
    )
    seen: list[object] = []
    cfg = Config.defaults()

    monkeypatch.setattr(capability_probe, "probe_core", lambda config: seen.append(config) or core)
    monkeypatch.setattr(
        capability_probe,
        "probe_overlay",
        lambda enabled: seen.append(enabled) or OverlayCapability.available(Backend.LAYER_SHELL),
    )

    caps = capability_probe.probe(cfg)

    assert seen == [cfg, cfg.feedback.overlay]
    assert caps.clipboard_backend == "wl-copy"
    assert caps.hotkey_access_ok is False
    assert caps.service_active == "active"
    assert caps.overlay.enabled is True
    assert caps.overlay.backend is Backend.LAYER_SHELL
