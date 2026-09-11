# SPDX-License-Identifier: GPL-3.0-or-later
"""The CLI-side binding-capture delegator.

Every case supplies a provider through the module's own ``platform`` keyword
(or the ``current_platform`` factory), so nothing here opens ``/dev/input``.
"""

from __future__ import annotations

import io

import pytest

from stenographer.cli.setup.binding_capture import capture_binding
from stenographer.lib.hotkey.errors import BindingCaptureError


class _Provider:
    """A provider that records the capture call it was handed."""

    def __init__(self, result: str | Exception = "KEY_F9") -> None:
        self.result = result
        self.calls: list[tuple] = []

    def capture_binding(self, stdin, device_path, *, timeout):
        self.calls.append((stdin, device_path, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize("timeout", [0.0, -1.0])
def test_a_non_positive_timeout_is_refused_before_the_provider_is_reached(timeout):
    provider = _Provider()

    with pytest.raises(ValueError, match="timeout must be positive"):
        capture_binding(io.StringIO(), "/dev/input/event3", timeout=timeout, platform=provider)

    assert provider.calls == []


def test_the_supplied_provider_receives_the_stream_device_and_timeout_unchanged():
    provider = _Provider("KEY_LEFTCTRL+KEY_F9")
    stdin = io.StringIO()

    result = capture_binding(stdin, "/dev/input/event3", timeout=2.5, platform=provider)

    assert result == "KEY_LEFTCTRL+KEY_F9"
    assert provider.calls == [(stdin, "/dev/input/event3", 2.5)]


def test_an_unset_device_reaches_the_provider_as_none_with_the_default_timeout():
    provider = _Provider()
    stdin = io.StringIO()

    assert capture_binding(stdin, None, platform=provider) == "KEY_F9"
    assert provider.calls == [(stdin, None, 15.0)]


def test_a_capture_failure_propagates_to_the_caller():
    provider = _Provider(BindingCaptureError("no readable input device"))

    with pytest.raises(BindingCaptureError, match="no readable input device"):
        capture_binding(io.StringIO(), None, timeout=15.0, platform=provider)

    assert len(provider.calls) == 1


def test_without_a_provider_the_active_platform_is_used(monkeypatch):
    from stenographer.lib import platform as platform_module

    provider = _Provider("KEY_F10")
    monkeypatch.setattr(platform_module, "current_platform", lambda: provider)
    stdin = io.StringIO()

    assert capture_binding(stdin, "/dev/input/event7", timeout=3.0) == "KEY_F10"
    assert provider.calls == [(stdin, "/dev/input/event7", 3.0)]
