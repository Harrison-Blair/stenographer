# SPDX-License-Identifier: GPL-3.0-or-later
"""Core capability assembly uses independent library collaborators."""

from types import SimpleNamespace

from stenographer.lib.config.models import Config
from stenographer.lib.diagnostics import capabilities
from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.transcribe import download


def test_probe_uses_model_cache_service_and_keeps_display_optional(monkeypatch):
    host = HostProbe(
        key_injector_ok=True,
        hotkey_access_ok=True,
        clipboard_ok=True,
        clipboard_backend="test-clipboard",
        cue_player=None,
        service_enabled=None,
        service_active=None,
    )
    monkeypatch.setattr(
        capabilities, "current_platform", lambda: SimpleNamespace(probe_host=lambda: host)
    )
    monkeypatch.setattr(capabilities, "_has_mic", lambda: True)
    requested = []

    def model_cached(model):
        requested.append(model)
        return True

    monkeypatch.setattr(download, "is_model_cached", model_cached)
    config = Config.defaults()
    result = capabilities.probe(config)

    assert requested == [config.asr.model]
    assert result.model_cached is True
    assert result.clipboard_backend == "test-clipboard"
    assert capabilities.missing_required(result) == []
    assert not hasattr(result, "overlay")
