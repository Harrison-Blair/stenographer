# SPDX-License-Identifier: GPL-3.0-or-later
"""The Linux provider's user-facing prose, pinned byte-for-byte.

``cli/doctor.py``, ``cli/setup.py``, ``cli/sounds.py``, and ``config.py`` now
print whatever :class:`HostGuidance` hands them, so the exact Linux wording is
only asserted here. Pure: no probe, no subprocess, no device.
"""

from __future__ import annotations

from stenographer.capabilities import REQUIRED
from stenographer.platform.linux.guidance import guidance, run_with_config

# Spelled out here rather than imported: the point is to pin the wording, so
# the expectation must not come from the module under test.
_XCLIP_HINT = "install xclip (the compositor lacks a data-control protocol; GNOME 46 and older)"


def test_capability_labels_and_fix_hints_cover_the_required_gate():
    g = guidance()
    assert set(g.capability_labels) == set(REQUIRED)
    # clipboard_ok is keyed by backend instead, so it has no flat hint.
    assert set(g.capability_fix_hints) == set(REQUIRED) - {"clipboard_ok"}


def test_capability_prose_is_the_shipped_wording():
    g = guidance()
    assert g.capability_labels == {
        "key_injector_ok": "/dev/uinput writable",
        "hotkey_access_ok": "input group membership",
        "has_mic": "microphone",
        "model_cached": "ASR model cached",
        "clipboard_ok": "clipboard",
    }
    assert g.capability_fix_hints == {
        "key_injector_ok": (
            "grant write access to /dev/uinput (udev rule or the uinput group), then re-login"
        ),
        "hotkey_access_ok": "sudo usermod -aG input $USER, then re-login",
        "has_mic": "no audio input device found; check the microphone / PortAudio",
        "model_cached": "run: stenographer model download",
    }
    assert g.clipboard_fix_hints == {"wl-copy": "install wl-clipboard", "x11": _XCLIP_HINT}
    assert g.clipboard_fix_hint_default == "install wl-clipboard"


def test_service_prose_is_the_shipped_systemd_wording():
    g = guidance()
    assert g.service_noun == "systemd unit"
    assert g.service_installer == "scripts/install.sh"
    assert g.service_unknown_detail == "cannot query the systemd user manager"
    assert g.service_start_command == "systemctl --user start stenographer.service"
    assert g.service_restart_command == "systemctl --user restart stenographer.service"
    assert g.service_log_command == "journalctl --user -u stenographer -f"


def test_hotkey_device_comment_matches_the_default_config_template():
    assert guidance().hotkey_device_comment == 'explicit /dev/input/event* path; "" = auto-detect'


def test_run_with_config_quotes_the_path_for_a_posix_shell():
    """A config path with a space must survive as one argument.

    Seen to FAIL against an unquoted ``f"STENOGRAPHER_CONFIG={path} ..."``
    (the space split the assignment from the command).
    """

    assert run_with_config("/home/a/config.toml") == (
        "STENOGRAPHER_CONFIG=/home/a/config.toml stenographer run"
    )
    assert run_with_config("/home/a b/config.toml") == (
        "STENOGRAPHER_CONFIG='/home/a b/config.toml' stenographer run"
    )
    assert run_with_config("/home/a'b/config.toml") == (
        """STENOGRAPHER_CONFIG='/home/a'"'"'b/config.toml' stenographer run"""
    )
