# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-logic tests for the doctor report: the gate decision and rendering only.

The gate (``stenographer.capabilities``) and its rendering (``cli/doctor.py``)
are exercised together here because the report is driven by ``REQUIRED``.

The environment probe itself is exercised by test_doctor_smoke.py (integration,
non-mocked) per the testing policy in AGENTS.md — nothing here stubs the
environment.

Host prose is an input, not a constant: ``render`` is handed a
``HostGuidance``. These cases pass the Linux wording explicitly so they assert
the same report on every OS; that the Linux provider really supplies those
strings is pinned by tests/platform/linux/test_guidance.py.
"""

from __future__ import annotations

import pathlib

from stenographer.capabilities import Capabilities, OverlayCapability, missing_required
from stenographer.cli import doctor
from stenographer.config import Config
from stenographer.platform.base import HostGuidance
from stenographer.status import Backend, UnavailableReason

# One config path for every render case. Asserted through ``str()`` because
# ``render`` interpolates the path: the rendered separator is the host's, so a
# POSIX literal would not match on Windows.
_CONFIG_PATH = pathlib.Path("/tmp/config.toml")

_XCLIP_HINT = "install xclip (the compositor lacks a data-control protocol; GNOME 46 and older)"

_GUIDANCE = HostGuidance(
    capability_labels={
        "key_injector_ok": "/dev/uinput writable",
        "hotkey_access_ok": "input group membership",
        "has_mic": "microphone",
        "model_cached": "ASR model cached",
        "clipboard_ok": "clipboard",
    },
    capability_fix_hints={
        "key_injector_ok": (
            "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
        ),
        "hotkey_access_ok": "sudo usermod -aG input $USER, then re-login",
        "has_mic": "no audio input device found; check the microphone / PortAudio",
        "model_cached": "run: stenographer model download",
    },
    clipboard_fix_hints={"wl-copy": "install wl-clipboard", "x11": _XCLIP_HINT},
    clipboard_fix_hint_default="install wl-clipboard",
    service_noun="systemd unit",
    service_name="stenographer.service",
    service_installer="scripts/install.sh",
    service_unknown_detail="cannot query the systemd user manager",
    service_start_command="systemctl --user start stenographer.service",
    service_restart_command="systemctl --user restart stenographer.service",
    service_log_command="journalctl --user -u stenographer -f",
    hotkey_device_comment='explicit /dev/input/event* path; "" = auto-detect',
    run_with_config=lambda path: f"STENOGRAPHER_CONFIG={path} stenographer run",
)

# A second host whose every word differs, so a hardcoded string in ``render``
# cannot hide behind the Linux wording above.
_OTHER_GUIDANCE = HostGuidance(
    capability_labels={
        "key_injector_ok": "paste injection",
        "hotkey_access_ok": "global hotkey hook",
        "has_mic": "audio capture",
        "model_cached": "recognizer weights",
        "clipboard_ok": "pasteboard",
    },
    capability_fix_hints={
        "key_injector_ok": "enable the injector",
        "hotkey_access_ok": "permit the hook",
        "has_mic": "attach a capture device",
        "model_cached": "fetch the weights",
    },
    clipboard_fix_hints={"native": "enable the pasteboard bridge"},
    clipboard_fix_hint_default="no pasteboard backend",
    service_noun="background agent",
    service_name="the stenographer agent",
    service_installer="the agent installer",
    service_unknown_detail="the agent manager did not answer",
    service_start_command="agentctl start",
    service_restart_command="agentctl restart",
    service_log_command="agentctl logs",
    hotkey_device_comment="opaque device id",
    run_with_config=lambda path: f"with-config {path}",
)


def _caps(**overrides) -> Capabilities:
    fields = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "cue_player": "pw-play",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": OverlayCapability.available(Backend.LAYER_SHELL),
    }
    fields.update(overrides)
    return Capabilities(**fields)


def test_missing_required_empty_when_all_present():
    assert missing_required(_caps()) == []


def test_missing_required_names_each_absent_capability():
    caps = _caps(key_injector_ok=False, model_cached=False)
    assert missing_required(caps) == ["key_injector_ok", "model_cached"]


def test_cue_player_is_not_required():
    assert missing_required(_caps(cue_player=None)) == []


def test_render_all_present():
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE)
    assert "all required capabilities present" in report
    assert "MISSING" not in report
    assert str(_CONFIG_PATH) in report
    assert "audio player: pw-play" in report
    assert report.count("  overlay: ") == 1
    assert "  overlay: layer-shell" in report


def test_render_missing_capability_carries_fix_hint():
    caps = _caps(model_cached=False, clipboard_ok=False)
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _GUIDANCE)
    assert "ASR model cached: MISSING — run: stenographer model download" in report
    assert "clipboard (wl-copy): MISSING — install wl-clipboard" in report
    assert "missing required capabilities: ASR model cached, clipboard" in report


def test_render_clipboard_line_names_the_detected_backend():
    report = doctor.render(
        _caps(clipboard_backend="x11"), Config.defaults(), _CONFIG_PATH, _GUIDANCE
    )
    assert "clipboard (x11): ok" in report

    report = doctor.render(
        _caps(clipboard_ok=False, clipboard_backend="x11"),
        Config.defaults(),
        _CONFIG_PATH,
        _GUIDANCE,
    )
    assert (
        "clipboard (x11): MISSING — install xclip "
        "(the compositor lacks a data-control protocol; GNOME 46 and older)"
    ) in report


def test_render_absent_cue_player_is_informational():
    report = doctor.render(_caps(cue_player=None), Config.defaults(), _CONFIG_PATH, _GUIDANCE)
    assert "audio player: none (sound cues disabled)" in report
    assert "all required capabilities present" in report


def test_service_status_is_not_required():
    assert missing_required(_caps(service_enabled=None, service_active=None)) == []


def test_format_service_status_installed():
    assert doctor.format_service_status("enabled", "active", _GUIDANCE) == "enabled, active"
    assert doctor.format_service_status("disabled", "inactive", _GUIDANCE) == "disabled, inactive"
    assert doctor.format_service_status("enabled", "failed", _GUIDANCE) == "enabled, failed"


def test_format_service_status_not_installed():
    # is-enabled yields nothing for an unknown unit; is-active still says "inactive"
    assert doctor.format_service_status(None, "inactive", _GUIDANCE) == (
        "not installed — run scripts/install.sh"
    )


def test_format_service_status_unreachable_manager():
    assert doctor.format_service_status(None, None, _GUIDANCE) == (
        "unknown (cannot query the systemd user manager)"
    )


def test_render_carries_service_status_line():
    report = doctor.render(_caps(), Config.defaults(), _CONFIG_PATH, _GUIDANCE)
    assert "systemd unit: enabled, active" in report

    report = doctor.render(
        _caps(service_enabled=None, service_active="inactive"),
        Config.defaults(),
        _CONFIG_PATH,
        _GUIDANCE,
    )
    assert "systemd unit: not installed — run scripts/install.sh" in report
    assert "all required capabilities present" in report


def test_render_takes_every_host_word_from_the_supplied_guidance():
    """No Linux prose may survive in ``render`` itself.

    Rendering a fully-missing gate under a host whose every label, hint, and
    service word differs must reproduce that host verbatim and leak none of the
    Linux wording. Seen to FAIL against the pre-change tree, where ``render``
    read module-level ``_LABELS`` / ``_FIX_HINTS`` / ``_CLIPBOARD_FIX_HINTS``
    dicts and hardcoded "systemd unit" and "run scripts/install.sh".
    """

    caps = _caps(
        key_injector_ok=False,
        hotkey_access_ok=False,
        has_mic=False,
        model_cached=False,
        clipboard_ok=False,
        clipboard_backend="native",
        service_enabled=None,
        service_active="inactive",
    )
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _OTHER_GUIDANCE)

    assert "  paste injection: MISSING — enable the injector" in report
    assert "  global hotkey hook: MISSING — permit the hook" in report
    assert "  audio capture: MISSING — attach a capture device" in report
    assert "  recognizer weights: MISSING — fetch the weights" in report
    assert "  pasteboard (native): MISSING — enable the pasteboard bridge" in report
    assert "  background agent: not installed — run the agent installer" in report
    for linux_word in (
        "/dev/uinput",
        "input group",
        "usermod",
        "wl-clipboard",
        "xclip",
        "systemd",
        "install.sh",
    ):
        assert linux_word not in report


def test_render_falls_back_to_the_hosts_default_clipboard_hint():
    """An unanticipated backend name still gets that host's hint, not another's."""

    caps = _caps(clipboard_ok=False, clipboard_backend="something-new")
    report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _OTHER_GUIDANCE)
    assert "  pasteboard (something-new): MISSING — no pasteboard backend" in report


def test_overlay_report_variants_are_informational_only():
    variants = (
        (OverlayCapability.disabled(), "disabled"),
        (OverlayCapability.available(Backend.LAYER_SHELL), "layer-shell"),
        (OverlayCapability.available(Backend.XWAYLAND), "XWayland fallback"),
        (
            OverlayCapability.unavailable(UnavailableReason.X_EXTENSIONS_UNAVAILABLE),
            "unavailable — XWayland requires the Shape and RandR extensions",
        ),
    )
    for overlay, expected in variants:
        caps = _caps(overlay=overlay)
        report = doctor.render(caps, Config.defaults(), _CONFIG_PATH, _GUIDANCE)
        assert report.count("  overlay: ") == 1
        assert f"  overlay: {expected}" in report
        assert missing_required(caps) == []
