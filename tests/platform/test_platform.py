# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider selection and Protocol conformance (pure; no device, display, or lock)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stenographer.capabilities import REQUIRED
from stenographer.platform import current_platform
from stenographer.platform.base import HostGuidance, HostProbe, Platform, UnsupportedPlatformError
from stenographer.platform.windows import WindowsPlatform

# Words no non-Linux provider may borrow: guidance is the platform's own prose.
_LINUX_ONLY_WORDS = (
    "systemctl",
    "journalctl",
    "install.sh",
    "/dev/uinput",
    "/dev/input",
    "usermod",
    "wl-clipboard",
    "xclip",
)


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
    # os.cpu_count() counts logical CPUs; the stub must not pass that off as a
    # physical-core count, so it says "cannot tell" and the core falls back.
    assert plat.physical_core_count() is None
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
    # The overlay supervisor asks for a transport before it spawns anything; a
    # stub that answered with a half-working one would spawn a helper Windows
    # cannot poll or terminate, instead of disabling the overlay.
    with pytest.raises(UnsupportedPlatformError):
        plat.helper_transport()


def test_providers_name_a_stop_reason_without_ever_raising():
    """The reason string is host vocabulary, and it is formatted in stop context.

    ``install_stop_handlers`` hands the core a label, not a signal number, so
    the naming happens inside the provider's own handler — a POSIX signal
    handler today, a console-control callback on Windows later. A raise there
    would swallow the stop instead of logging it, so an unnameable code must
    degrade to a label rather than blow up. Seen to FAIL against an unguarded
    ``signal.Signals(signum).name`` (ValueError: 999 is not a valid Signals).
    """

    import signal

    from stenographer.platform.windows import signal_reason as windows_reason

    providers = [windows_reason]
    if sys.platform.startswith("linux"):
        from stenographer.platform.linux import signal_reason as linux_reason

        providers.append(linux_reason)

    for reason in providers:
        assert reason(signal.SIGINT) == "SIGINT"
        assert reason(signal.SIGTERM) == "SIGTERM"
        assert "999" in reason(999)


def test_windows_stub_returns_complete_and_non_posix_guidance():
    """The stub must still answer every guidance question, in its own words.

    A missing capability key would make ``doctor`` render a KeyError instead of
    a report, and a borrowed systemd/POSIX string would be a lie on Windows.
    Seen to FAIL against a stub with no ``guidance`` (AttributeError) and
    against one returning the Linux wording.
    """

    g = WindowsPlatform().guidance()
    assert isinstance(g, HostGuidance)
    assert set(g.capability_labels) == set(REQUIRED)
    assert set(g.capability_fix_hints) == set(REQUIRED) - {"clipboard_ok"}
    assert g.clipboard_fix_hint_default
    assert g.run_with_config("C:/Users/alice/config.toml") == (
        'set "STENOGRAPHER_CONFIG=C:/Users/alice/config.toml" && stenographer run'
    )

    prose = " ".join(
        (
            *g.capability_labels.values(),
            *g.capability_fix_hints.values(),
            *g.clipboard_fix_hints.values(),
            g.clipboard_fix_hint_default,
            g.service_noun,
            g.service_installer,
            g.service_unknown_detail,
            g.service_start_command,
            g.service_restart_command,
            g.service_log_command,
            g.hotkey_device_comment,
            g.run_with_config("C:/config.toml"),
        )
    )
    for word in _LINUX_ONLY_WORDS:
        assert word not in prose, word


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
