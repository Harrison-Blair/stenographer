# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux provider selection and Protocol conformance (pure; no device or lock)."""

from __future__ import annotations

import signal
import sys

import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.hotkey.binding import parse_binding
from stenographer.lib.platform import current_platform
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.platform.platform import Platform


def test_current_platform_matches_host_and_is_cached():
    platform = current_platform()

    assert isinstance(platform, Platform)
    assert platform.name == "linux"
    assert current_platform() is platform


def test_linux_provider_conforms_to_platform_protocol():
    from stenographer.lib.platform.linux.provider import LinuxPlatform

    assert isinstance(LinuxPlatform(), Platform)


def test_linux_provider_parses_the_shipped_default_binding():
    from stenographer.lib.platform.linux.provider import LinuxPlatform

    platform = LinuxPlatform()
    assert parse_binding(Config.defaults().hotkey.binding, platform.keys())


def test_linux_provider_resolves_the_shared_key_vocabulary():
    from stenographer.lib.platform.linux.provider import LinuxPlatform

    keys = LinuxPlatform().keys()
    for binding in ("KEY_RIGHTCTRL", "KEY_RIGHTALT"):
        assert keys.name(keys.code(binding)) == binding


def test_linux_provider_names_stop_reasons_without_raising():
    from stenographer.lib.platform.linux.support import signal_reason

    assert signal_reason(signal.SIGINT) == "SIGINT"
    assert signal_reason(signal.SIGTERM) == "SIGTERM"
    assert "999" in signal_reason(999)


def test_current_platform_rejects_win32(monkeypatch):
    current_platform.cache_clear()
    try:
        monkeypatch.setattr(sys, "platform", "win32")
        with pytest.raises(UnsupportedPlatformError, match="win32"):
            current_platform()
    finally:
        current_platform.cache_clear()


def test_current_platform_rejects_darwin(monkeypatch):
    current_platform.cache_clear()
    try:
        monkeypatch.setattr(sys, "platform", "darwin")
        with pytest.raises(UnsupportedPlatformError, match="darwin"):
            current_platform()
    finally:
        current_platform.cache_clear()


def test_current_platform_rejects_an_unknown_host(monkeypatch):
    current_platform.cache_clear()
    try:
        monkeypatch.setattr(sys, "platform", "aix")
        with pytest.raises(UnsupportedPlatformError, match="aix"):
            current_platform()
    finally:
        current_platform.cache_clear()


def test_stop_handlers_register_and_name_both_reasons():
    """The provider hands the core signal names, not numeric values."""
    provider = current_platform()
    signals = (signal.SIGINT, signal.SIGTERM)
    saved = {sig: signal.getsignal(sig) for sig in signals}
    try:
        reasons: list[str] = []
        provider.install_stop_handlers(reasons.append)
        for sig in signals:
            installed = signal.getsignal(sig)
            assert callable(installed) and installed is not saved[sig]
            installed(sig, None)
        assert reasons == [sig.name for sig in signals]
    finally:
        for sig, previous in saved.items():
            signal.signal(sig, previous)
