# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the doctor report: decision and rendering only.

The environment probe itself is exercised by test_doctor_smoke.py (integration,
non-mocked) per spec §6 — nothing here stubs the environment.
"""

from __future__ import annotations

import pathlib

from stenographer.cli import doctor
from stenographer.config import Config
from stenographer.status import Backend, UnavailableReason


def _caps(**overrides) -> doctor.Capabilities:
    fields = {
        "uinput_writable": True,
        "input_group": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard": True,
        "clipboard_backend": "wl-copy",
        "audio_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": doctor.OverlayCapability.available(Backend.LAYER_SHELL),
    }
    fields.update(overrides)
    return doctor.Capabilities(**fields)


def test_missing_required_empty_when_all_present():
    assert doctor.missing_required(_caps()) == []


def test_missing_required_names_each_absent_capability():
    caps = _caps(uinput_writable=False, model_cached=False)
    assert doctor.missing_required(caps) == ["uinput_writable", "model_cached"]


def test_audio_player_is_not_required():
    assert doctor.missing_required(_caps(audio_player=None)) == []


def test_render_all_present():
    report = doctor.render(_caps(), Config.defaults(), pathlib.Path("/tmp/config.toml"))
    assert "all required capabilities present" in report
    assert "MISSING" not in report
    assert "/tmp/config.toml" in report
    assert "audio player: pw-play" in report
    assert report.count("  overlay: ") == 1
    assert "  overlay: layer-shell" in report


def test_render_missing_capability_carries_fix_hint():
    caps = _caps(model_cached=False, clipboard=False)
    report = doctor.render(caps, Config.defaults(), pathlib.Path("/tmp/config.toml"))
    assert "ASR model cached: MISSING — run: stenographer model download" in report
    assert "clipboard (wl-copy): MISSING — install wl-clipboard" in report
    assert "missing required capabilities: model_cached, clipboard" in report


def test_render_clipboard_line_names_the_detected_backend():
    report = doctor.render(_caps(clipboard_backend="x11"), Config.defaults(), pathlib.Path("/x"))
    assert "clipboard (x11): ok" in report

    report = doctor.render(
        _caps(clipboard=False, clipboard_backend="x11"), Config.defaults(), pathlib.Path("/x")
    )
    assert (
        "clipboard (x11): MISSING — install xclip "
        "(the compositor lacks a data-control protocol; GNOME 46 and older)"
    ) in report


def test_render_absent_audio_player_is_informational():
    report = doctor.render(_caps(audio_player=None), Config.defaults(), pathlib.Path("/x"))
    assert "audio player: none (sound cues disabled)" in report
    assert "all required capabilities present" in report


def test_service_status_is_not_required():
    assert doctor.missing_required(_caps(service_enabled=None, service_active=None)) == []


def test_format_service_status_installed():
    assert doctor.format_service_status("enabled", "active") == "enabled, active"
    assert doctor.format_service_status("disabled", "inactive") == "disabled, inactive"
    assert doctor.format_service_status("enabled", "failed") == "enabled, failed"


def test_format_service_status_not_installed():
    # is-enabled yields nothing for an unknown unit; is-active still says "inactive"
    assert doctor.format_service_status(None, "inactive") == (
        "not installed — run scripts/install.sh"
    )


def test_format_service_status_unreachable_manager():
    assert doctor.format_service_status(None, None) == (
        "unknown (cannot query the systemd user manager)"
    )


def test_render_carries_service_status_line():
    report = doctor.render(_caps(), Config.defaults(), pathlib.Path("/x"))
    assert "systemd unit: enabled, active" in report

    report = doctor.render(
        _caps(service_enabled=None, service_active="inactive"),
        Config.defaults(),
        pathlib.Path("/x"),
    )
    assert "systemd unit: not installed — run scripts/install.sh" in report
    assert "all required capabilities present" in report


def test_overlay_report_variants_are_informational_only():
    variants = (
        (doctor.OverlayCapability.disabled(), "disabled"),
        (doctor.OverlayCapability.available(Backend.LAYER_SHELL), "layer-shell"),
        (doctor.OverlayCapability.available(Backend.XWAYLAND), "XWayland fallback"),
        (
            doctor.OverlayCapability.unavailable(UnavailableReason.X_EXTENSIONS_UNAVAILABLE),
            "unavailable — XWayland requires the Shape and RandR extensions",
        ),
    )
    for overlay, expected in variants:
        caps = _caps(overlay=overlay)
        report = doctor.render(caps, Config.defaults(), pathlib.Path("/x"))
        assert report.count("  overlay: ") == 1
        assert f"  overlay: {expected}" in report
        assert doctor.missing_required(caps) == []
