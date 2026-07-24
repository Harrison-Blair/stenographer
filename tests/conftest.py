# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest configuration and environment isolation."""

from __future__ import annotations

import os
import pathlib
import sys
import types
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_runtime_dirs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep CLI state and lock files out of user-owned directories."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


def _install_sounddevice_stub() -> None:
    """Avoid initializing real PortAudio while collecting unit tests."""

    module = types.ModuleType("sounddevice")

    class PortAudioError(Exception):
        """Test substitute for :class:`sounddevice.PortAudioError`."""

    class CallbackFlags:
        """Minimal callback status used by recorder unit tests."""

        def __init__(self) -> None:
            self.input_overflow = False

    class Default:
        device = (-1, -1)

    def query_devices(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def input_stream(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unit test attempted to open a real audio stream")

    module.PortAudioError = PortAudioError
    module.CallbackFlags = CallbackFlags
    module.default = Default()
    module.query_devices = query_devices
    module.InputStream = input_stream
    sys.modules["sounddevice"] = module


if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    _install_sounddevice_stub()
