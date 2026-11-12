# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability assembly from the host, the microphone, the model cache, and the overlay."""

from types import SimpleNamespace

from stenographer.cli.shared import capabilities
from stenographer.cli.shared.capabilities import Capabilities
from stenographer.lib.config.models import Config
from stenographer.lib.platform.host_probe import HostProbe
from stenographer.lib.transcribe import bark_download
from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.protocol.backend import Backend


def test_probe_keeps_the_host_facts_and_gates_on_the_model_cache_not_the_overlay(monkeypatch):
    host = HostProbe(
        key_injector_ok=True,
        hotkey_access_ok=True,
        clipboard_ok=True,
        clipboard_backend="test-clipboard",
        clipboard_read_ok=False,
        cue_player=None,
        service_enabled=None,
        service_active=None,
    )
    monkeypatch.setattr(
        capabilities, "current_platform", lambda: SimpleNamespace(probe_host=lambda: host)
    )
    monkeypatch.setattr(capabilities, "_mic_issue", lambda: None)
    overlay_args = []

    def probe_overlay(enabled):
        overlay_args.append(enabled)
        return OverlayCapability.available(Backend.LAYER_SHELL)

    monkeypatch.setattr(capabilities, "probe_overlay", probe_overlay)
    requested = []

    def model_cached(*args, **kwargs):
        requested.append((args, kwargs))
        return True

    monkeypatch.setattr(bark_download, "is_model_cached", model_cached)
    cfg = Config.defaults()
    result = capabilities.probe(cfg)

    # The Bark probe takes no model id: one model, one fixed directory.
    assert requested == [((), {})]
    assert result.model_cached is True
    assert result.clipboard_backend == "test-clipboard"
    # Restoring the clipboard is a convenience: its reader is never required.
    assert result.clipboard_read_ok is False
    assert capabilities.missing_required(result) == []
    assert overlay_args == [cfg.feedback.overlay]
    assert result.overlay.backend is Backend.LAYER_SHELL


def test_the_microphone_gate_reads_the_shared_source_listing(monkeypatch):
    # One listing answers the whole program; the gate is the pure reading of it,
    # so a missing tool or a host with no microphone fails the gate with its reason.
    from stenographer.lib.audio import probe as audio_probe
    from stenographer.lib.platform.mic_capture import InputSource, InputSources

    monkeypatch.setattr(capabilities, "current_platform", lambda: SimpleNamespace(probe_host=_host))
    monkeypatch.setattr(
        capabilities, "probe_overlay", lambda _enabled: OverlayCapability.disabled()
    )
    monkeypatch.setattr(bark_download, "is_model_cached", lambda: True)
    cases = [
        (InputSources(error="pw-record is not installed"), False, "pw-record is not installed"),
        (InputSources(), False, "no microphone found"),
        (InputSources(sources=(InputSource("mic", "USB mic"),)), True, None),
    ]
    for query, has_mic, issue in cases:
        monkeypatch.setattr(audio_probe, "query_devices", lambda query=query: query)
        result = capabilities.probe(Config.defaults())
        assert (result.has_mic, result.mic_issue) == (has_mic, issue)


def _host() -> HostProbe:
    return HostProbe(
        key_injector_ok=True,
        hotkey_access_ok=True,
        clipboard_ok=True,
        clipboard_backend="test-clipboard",
        clipboard_read_ok=True,
        cue_player=None,
        service_enabled=None,
        service_active=None,
    )


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
            clipboard_read_ok=False,
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
