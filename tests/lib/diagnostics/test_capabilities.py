# SPDX-License-Identifier: GPL-3.0-or-later
"""Core capability assembly uses independent library collaborators."""

from types import SimpleNamespace

from stenographer.lib.config.models import Config
from stenographer.lib.diagnostics import capabilities
from stenographer.lib.diagnostics.capability_result import Capabilities
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


def test_the_microphone_gate_reads_the_shared_device_enumeration(monkeypatch):
    # One enumeration answers the whole program; the gate is the pure reading
    # of it, so a host with only output devices must fail the gate.
    from stenographer.lib.audio import probe as audio_probe
    from stenographer.lib.audio.device_query import DeviceQuery

    outputs_only = DeviceQuery(
        devices=({"name": "speakers", "max_input_channels": 0},), default_device=(None, 0)
    )
    monkeypatch.setattr(audio_probe, "query_devices", lambda: outputs_only)
    assert capabilities._has_mic() is False

    with_input = DeviceQuery(
        devices=(
            {"name": "speakers", "max_input_channels": 0},
            {"name": "usb mic", "max_input_channels": 2},
        ),
        default_device=(1, 0),
    )
    monkeypatch.setattr(audio_probe, "query_devices", lambda: with_input)
    assert capabilities._has_mic() is True


def test_only_the_absent_required_capabilities_are_named():
    def host(**present):
        absent = {
            "key_injector_ok": False,
            "hotkey_access_ok": False,
            "has_mic": False,
            "model_cached": False,
            "clipboard_ok": False,
        }
        return Capabilities(
            **{**absent, **present},
            clipboard_backend="",
            cue_player=None,
            service_enabled=None,
            service_active=None,
        )

    assert capabilities.missing_required(host()) == list(capabilities.REQUIRED)
    assert capabilities.missing_required(host(has_mic=True)) == [
        name for name in capabilities.REQUIRED if name != "has_mic"
    ]
    assert "has_mic" not in capabilities.missing_required(host(has_mic=True))
    assert (
        capabilities.missing_required(
            host(
                key_injector_ok=True,
                hotkey_access_ok=True,
                has_mic=True,
                model_cached=True,
                clipboard_ok=True,
            )
        )
        == []
    )
