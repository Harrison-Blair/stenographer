# SPDX-License-Identifier: GPL-3.0-or-later
"""Which overlay host each OS gets, and what that host actually offers.

``current_platform`` is the single dispatch point every overlay caller reaches
the host through, so the mapping from ``sys.platform`` to a provider class is
the contract. It is cached for the life of the process, which makes clearing
the cache part of the test rather than an implementation detail.

The two unimplemented hosts are asserted just as strictly: an empty backend
list and a refusing transport are what keep the supervisor from spawning a
helper that could never draw anything.
"""

from __future__ import annotations

import sys

import pytest

from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.overlay.platform import current_platform
from stenographer.overlay.platform.guidance import OverlayGuidance
from stenographer.overlay.platform.linux.linux_helper_transport import LinuxHelperTransport
from stenographer.overlay.platform.linux.provider import LinuxOverlayPlatform
from stenographer.overlay.platform.macos.provider import MacOSOverlayPlatform
from stenographer.overlay.platform.overlay_backend_spec import OverlayBackendSpec
from stenographer.overlay.platform.windows.provider import WindowsOverlayPlatform
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason


@pytest.fixture
def uncached_platform():
    """``current_platform`` is process-cached; a dispatch test owns that cache."""
    current_platform.cache_clear()
    yield
    current_platform.cache_clear()


@pytest.mark.parametrize(
    ("platform", "provider"),
    [
        ("linux", LinuxOverlayPlatform),
        ("linux2", LinuxOverlayPlatform),
        ("win32", WindowsOverlayPlatform),
        ("darwin", MacOSOverlayPlatform),
    ],
)
def test_each_supported_host_resolves_to_its_own_overlay_provider(
    monkeypatch, uncached_platform, platform, provider
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert isinstance(current_platform(), provider)


def test_an_unknown_host_is_refused_by_name_rather_than_guessed(
    monkeypatch, uncached_platform
) -> None:
    monkeypatch.setattr(sys, "platform", "freebsd14")

    with pytest.raises(UnsupportedPlatformError, match="freebsd14"):
        current_platform()


def test_the_resolved_provider_is_reused_for_the_life_of_the_process(
    uncached_platform,
) -> None:
    assert current_platform() is current_platform()


def test_linux_offers_a_real_transport_and_both_backends_in_preference_order() -> None:
    platform = LinuxOverlayPlatform()

    assert isinstance(platform.helper_transport(), LinuxHelperTransport)
    specs = platform.overlay_backends()
    assert all(isinstance(spec, OverlayBackendSpec) for spec in specs)
    assert tuple(spec.backend for spec in specs) == (Backend.LAYER_SHELL, Backend.XWAYLAND)


def test_linux_guidance_names_both_backends_and_a_fix_for_every_x_refusal() -> None:
    guidance = LinuxOverlayPlatform().guidance()

    assert isinstance(guidance, OverlayGuidance)
    assert guidance.overlay_backend_labels == {
        "layer-shell": "layer-shell",
        "xwayland": "XWayland fallback",
    }
    assert set(guidance.overlay_fix_hints) == {
        UnavailableReason.NO_X_DISPLAY,
        UnavailableReason.X_CONNECT_FAILED,
        UnavailableReason.X_ARGB_UNAVAILABLE,
        UnavailableReason.X_EXTENSIONS_UNAVAILABLE,
        UnavailableReason.BACKEND_DEPENDENCY_MISSING,
    }
    assert "layer-shell or XWayland" in guidance.overlay_fix_hint_default


@pytest.mark.parametrize(
    ("provider", "host"),
    [(MacOSOverlayPlatform, "macOS"), (WindowsOverlayPlatform, "Windows")],
)
def test_a_host_without_an_overlay_refuses_to_spawn_a_helper(provider, host) -> None:
    """Seen to matter for the supervisor: an empty backend list alone would let
    it spawn a child that can only ever answer ``unavailable``.
    """
    platform = provider()

    assert platform.overlay_backends() == ()
    with pytest.raises(UnsupportedPlatformError, match=host):
        platform.helper_transport()


@pytest.mark.parametrize(
    ("provider", "host"),
    [(MacOSOverlayPlatform, "macOS"), (WindowsOverlayPlatform, "Windows")],
)
def test_a_host_without_an_overlay_still_explains_itself_to_doctor(provider, host) -> None:
    guidance = provider().guidance()

    assert isinstance(guidance, OverlayGuidance)
    assert guidance.overlay_backend_labels == {}
    assert guidance.overlay_fix_hints == {}
    assert guidance.overlay_fix_hint_default == f"the overlay is not available on {host} yet"
