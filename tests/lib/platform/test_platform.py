# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider selection and Protocol conformance (pure; no device, display, or lock)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stenographer.lib.diagnostics.capabilities import REQUIRED
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.host_guidance import HostGuidance
from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.platform.platform import Platform
from stenographer.lib.platform.windows.provider import WindowsPlatform
from stenographer.overlay.platform.windows.provider import WindowsOverlayPlatform

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
    expected = {"linux": "linux", "win32": "windows", "darwin": "macos"}[sys.platform]
    assert plat.name == expected
    assert current_platform() is plat


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux provider")
def test_linux_provider_conforms_to_platform_protocol():
    from stenographer.lib.platform.linux.provider import LinuxPlatform

    assert isinstance(LinuxPlatform(), Platform)


def test_windows_stub_conforms_and_reports_everything_unavailable():
    # The stub must import on every host (the Linux bundle collects it) and
    # make doctor's REQUIRED gate fail closed rather than crash.
    plat = WindowsPlatform()
    assert isinstance(plat, Platform)
    probe = plat.probe_host()
    assert isinstance(probe, HostProbe)
    assert not (probe.key_injector_ok or probe.hotkey_access_ok or probe.clipboard_ok)
    assert WindowsOverlayPlatform().overlay_backends() == ()
    assert plat.hotkey_devices() == []
    # os.cpu_count() counts logical CPUs; the stub must not pass that off as a
    # physical-core count, so it says "cannot tell" and the core falls back.
    assert plat.physical_core_count() is None
    # No journal to defer timestamps to, whatever the environment says.
    assert plat.journal_attached({"JOURNAL_STREAM": "8:123456"}) is False
    # The KEY_* vocabulary is core data, so the stub speaks it even with no
    # backend: a binding must parse and render wherever config is read.
    assert plat.keys().code("KEY_RIGHTCTRL") == 97
    assert plat.keys().name(29) == "KEY_LEFTCTRL"
    with pytest.raises(KeyError):
        plat.keys().code("KEY_NOT_A_REAL_KEY")
    plat.notifier().error("must not raise")
    plat.notifier().info("must not raise")
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
        WindowsOverlayPlatform().helper_transport()


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

    from stenographer.lib.platform.macos.support import signal_reason as macos_reason
    from stenographer.lib.platform.windows.support import signal_reason as windows_reason

    providers = [windows_reason, macos_reason]
    if sys.platform.startswith("linux"):
        from stenographer.lib.platform.linux.support import signal_reason as linux_reason

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
    from stenographer.lib.config.models import Config
    from stenographer.lib.hotkey.binding import parse_binding

    default = Config.defaults().hotkey.binding
    for provider in (current_platform(), WindowsPlatform()):
        assert parse_binding(default, provider.keys()), provider.name


def test_current_platform_dispatches_per_host_and_refuses_the_unknown(monkeypatch):
    """The dispatch itself, exercised for the two hosts this machine is not.

    Only ``sys.platform`` is steered (the branch's own input); each provider is
    then really constructed. The cache is cleared on both sides so neither the
    steered lookups nor the host's own provider leak between tests.
    """
    from stenographer.lib.platform.macos.provider import MacOSPlatform

    current_platform.cache_clear()
    try:
        monkeypatch.setattr(sys, "platform", "win32")
        assert isinstance(current_platform(), WindowsPlatform)

        current_platform.cache_clear()
        monkeypatch.setattr(sys, "platform", "darwin")
        assert isinstance(current_platform(), MacOSPlatform)

        current_platform.cache_clear()
        monkeypatch.setattr(sys, "platform", "aix")
        with pytest.raises(UnsupportedPlatformError, match="aix"):
            current_platform()
    finally:
        current_platform.cache_clear()


def test_macos_stub_conforms_and_reports_everything_unavailable():
    """The macOS mirror of the Windows stub contract.

    The stub must import and answer on every host (the Linux bundle collects
    it), fail closed on each missing backend, and still hand doctor a complete
    ``HostProbe`` rather than crashing it.
    """
    import io
    import threading

    from stenographer.lib.hotkey.errors import BindingCaptureError
    from stenographer.lib.platform.macos.provider import MacOSPlatform
    from stenographer.lib.platform.multiprocessing_asr_transport import MultiprocessingAsrTransport
    from stenographer.lib.platform.null_notifier import NullNotifier
    from stenographer.lib.platform.preview_audio import PortAudioCuePlayer

    plat = MacOSPlatform()
    assert isinstance(plat, Platform)
    assert plat.runtime_dir({"XDG_STATE_HOME": "/xdg"}) == Path("/xdg/stenographer/runtime")
    # The KEY_* vocabulary is core data, so the stub speaks it with no backend.
    assert plat.keys().code("KEY_RIGHTCTRL") == 97
    assert plat.hotkey_devices() == []
    assert isinstance(plat.notifier(), NullNotifier)
    # Construction is hardware-free: PortAudio is imported at playback only.
    assert isinstance(plat.cue_player(), PortAudioCuePlayer)
    assert isinstance(plat.asr_transport(), MultiprocessingAsrTransport)
    assert plat.physical_core_count() is None
    assert plat.journal_attached({"JOURNAL_STREAM": "8:123456"}) is False
    assert plat.restart_service() == (False, "no service manager integration on macOS")

    probe = plat.probe_host()
    assert isinstance(probe, HostProbe)
    assert not (probe.key_injector_ok or probe.hotkey_access_ok or probe.clipboard_ok)
    assert probe.clipboard_backend == "unavailable"
    assert probe.cue_player is None
    assert probe.service_enabled is None
    assert probe.service_active is None

    # Capture is refused in the setup flow's own vocabulary, not as a generic
    # platform error, so quick setup reports it instead of aborting.
    with pytest.raises(BindingCaptureError):
        plat.capture_binding(io.StringIO(), None, timeout=1.0)
    with pytest.raises(UnsupportedPlatformError):
        plat.hotkey_listener(
            chord=frozenset({97}),
            device=None,
            on_start=lambda: None,
            on_stop=lambda: None,
            lock=threading.RLock(),
        )
    with pytest.raises(UnsupportedPlatformError):
        plat.key_injector()
    with pytest.raises(UnsupportedPlatformError):
        plat.clipboard_writer("unavailable")
    with pytest.raises(UnsupportedPlatformError):
        plat.single_instance_lock()


def test_macos_stub_returns_complete_and_non_posix_guidance():
    """Same gate as the Windows stub: every capability key present, in macOS words."""
    from stenographer.lib.platform.macos.provider import MacOSPlatform

    g = MacOSPlatform().guidance()
    assert isinstance(g, HostGuidance)
    assert set(g.capability_labels) == set(REQUIRED)
    assert set(g.capability_fix_hints) == set(REQUIRED) - {"clipboard_ok"}
    assert g.clipboard_fix_hint_default
    # macOS has a POSIX shell, so the config override is a shell prefix — with
    # the path quoted, unlike the Windows `set "VAR=..."` form.
    assert g.run_with_config("/Users/alice/my config.toml") == (
        "STENOGRAPHER_CONFIG='/Users/alice/my config.toml' stenographer run"
    )

    prose = " ".join(
        (
            *g.capability_labels.values(),
            *g.capability_fix_hints.values(),
            g.clipboard_fix_hint_default,
            g.service_noun,
            g.service_installer,
            g.service_unknown_detail,
            g.service_start_command,
            g.service_restart_command,
            g.service_log_command,
            g.hotkey_device_comment,
        )
    )
    for word in _LINUX_ONLY_WORDS:
        assert word not in prose, word


def test_windows_stub_refuses_the_remaining_backends_and_names_its_directories():
    import io
    import threading

    from stenographer.lib.hotkey.errors import BindingCaptureError
    from stenographer.lib.platform.multiprocessing_asr_transport import MultiprocessingAsrTransport
    from stenographer.lib.platform.preview_audio import PortAudioCuePlayer

    plat = WindowsPlatform()
    home = Path("C:/Users/alice")
    assert plat.state_dir({"XDG_STATE_HOME": "/xdg"}, home) == Path("/xdg/stenographer")
    assert plat.state_dir({}, home) == home / "AppData/Local/stenographer"
    assert plat.runtime_dir({"LOCALAPPDATA": "C:/Users/alice/AppData/Local"}) == Path(
        "C:/Users/alice/AppData/Local/stenographer"
    )
    # No LOCALAPPDATA: the fallback is anchored on the real home, not on cwd.
    assert plat.runtime_dir({}) == Path.home() / "AppData/Local/stenographer"

    assert isinstance(plat.cue_player(), PortAudioCuePlayer)
    assert isinstance(plat.asr_transport(), MultiprocessingAsrTransport)
    assert plat.restart_service() == (False, "no service manager integration on Windows")
    with pytest.raises(BindingCaptureError):
        plat.capture_binding(io.StringIO(), None, timeout=1.0)
    with pytest.raises(UnsupportedPlatformError):
        plat.hotkey_listener(
            chord=frozenset({97}),
            device=None,
            on_start=lambda: None,
            on_stop=lambda: None,
            lock=threading.RLock(),
        )


def test_stop_handlers_really_register_and_name_the_reason_they_were_given():
    """``install_stop_handlers`` is registration, so it is tested by registering.

    The handler is installed for real on this process and invoked directly (no
    signal is sent), which is the only way to see that the provider hands the
    core a *name* rather than a number. Every previous disposition is restored.
    """
    import signal

    from stenographer.lib.platform.macos.provider import MacOSPlatform

    both = (signal.SIGINT, signal.SIGTERM)
    saved = {sig: signal.getsignal(sig) for sig in both}
    try:
        for provider, expected in (
            (WindowsPlatform(), (signal.SIGINT,)),  # console-control handler pending
            (MacOSPlatform(), both),
            (current_platform(), (signal.SIGINT,) if sys.platform == "win32" else both),
        ):
            for sig in both:
                signal.signal(sig, saved[sig])
            reasons: list[str] = []
            provider.install_stop_handlers(reasons.append)
            for sig in both:
                installed = signal.getsignal(sig)
                if sig not in expected:
                    assert installed is saved[sig], provider.name
                    continue
                assert callable(installed) and installed is not saved[sig], provider.name
                installed(sig, None)
            assert reasons == [sig.name for sig in expected], provider.name
    finally:
        for sig, previous in saved.items():
            signal.signal(sig, previous)
