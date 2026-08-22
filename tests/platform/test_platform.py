# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider selection and Protocol conformance (pure; no device, display, or lock)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stenographer.platform import current_platform
from stenographer.platform.base import HostProbe, Platform, UnsupportedPlatformError
from stenographer.platform.windows import WindowsPlatform


def test_current_platform_matches_host_and_is_cached():
    plat = current_platform()
    assert isinstance(plat, Platform)
    expected = "linux" if sys.platform.startswith("linux") else "windows"
    assert plat.name == expected
    assert current_platform() is plat


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux provider")
def test_linux_provider_conforms_to_platform_protocol():
    from stenographer.platform.linux import LinuxPlatform

    assert isinstance(LinuxPlatform(), Platform)


def test_windows_stub_conforms_and_reports_everything_unavailable():
    # The stub must import on every host (the Linux bundle collects it) and
    # make doctor's REQUIRED gate fail closed rather than crash.
    plat = WindowsPlatform()
    assert isinstance(plat, Platform)
    probe = plat.probe_host()
    assert isinstance(probe, HostProbe)
    assert not (probe.key_injector_ok or probe.hotkey_access_ok or probe.clipboard_ok)
    assert plat.overlay_backends() == ()
    assert plat.hotkey_devices() == []
    assert plat.cue_player() is None
    # The KEY_* vocabulary is core data, so the stub speaks it even with no
    # backend: a binding must parse and render wherever config is read.
    assert plat.keys().code("KEY_RIGHTCTRL") == 97
    assert plat.keys().name(29) == "KEY_LEFTCTRL"
    with pytest.raises(KeyError):
        plat.keys().code("KEY_NOT_A_REAL_KEY")
    plat.notifier().error("must not raise")
    with pytest.raises(UnsupportedPlatformError):
        plat.key_injector()
    with pytest.raises(UnsupportedPlatformError):
        plat.clipboard_writer("unavailable")
    with pytest.raises(UnsupportedPlatformError):
        plat.single_instance_lock()


def test_windows_stub_directories_honour_xdg_then_windows_conventions():
    plat = WindowsPlatform()
    home = Path("C:/Users/alice")
    assert plat.config_path({"XDG_CONFIG_HOME": "/xdg"}, home) == Path(
        "/xdg/stenographer/config.toml"
    )
    assert plat.config_path({"APPDATA": "C:/Users/alice/AppData/Roaming"}, home) == Path(
        "C:/Users/alice/AppData/Roaming/stenographer/config.toml"
    )
    assert plat.config_path({}, home) == home / "AppData/Roaming/stenographer/config.toml"
    assert plat.state_dir({"LOCALAPPDATA": "C:/Users/alice/AppData/Local"}, home) == Path(
        "C:/Users/alice/AppData/Local/stenographer"
    )


def test_every_provider_parses_the_shipped_default_binding():
    """The guard for the Windows CI break: a provider that cannot parse the
    default binding fails here, on Linux, instead of only on the Windows runner.

    Seen to FAIL against the stub's old empty key table (BindingError: unknown
    key 'KEY_RIGHTCTRL').
    """
    from stenographer.config import Config
    from stenographer.hotkey import parse_binding

    default = Config.defaults().hotkey.binding
    for provider in (current_platform(), WindowsPlatform()):
        assert parse_binding(default, provider.keys()), provider.name
