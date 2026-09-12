# SPDX-License-Identifier: GPL-3.0-or-later
"""The startup banner: every configured key is reported, and prose is never logged.

The banner is the only record of what the daemon was actually configured with,
so each of its six lines is asserted field by field. ``asr.hotwords`` and
``asr.initial_prompt`` are the two keys that can hold arbitrary user prose;
they must appear only as sizes.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from types import SimpleNamespace

import pytest

from stenographer.cli.run.banner import _log_banner, _overlay_backend_name, _shown
from stenographer.cli.shared.capabilities import Capabilities
from stenographer.lib.config.models import Config
from stenographer.overlay.capabilities.models import OverlayCapability
from stenographer.overlay.protocol.backend import Backend
from stenographer.overlay.protocol.unavailablereason import UnavailableReason

_CONFIG_PATH = pathlib.PurePosixPath("/cfg/config.toml")


def _capabilities(**overrides) -> Capabilities:
    state = {
        "key_injector_ok": True,
        "hotkey_access_ok": True,
        "has_mic": True,
        "model_cached": True,
        "clipboard_ok": True,
        "clipboard_backend": "wl-copy",
        "cue_player": "pulse",
        "service_enabled": "enabled",
        "service_active": "active",
        "overlay": OverlayCapability.available(Backend.LAYER_SHELL),
    }
    state.update(overrides)
    return Capabilities(**state)


def _platform(cores: int | None = 6) -> SimpleNamespace:
    return SimpleNamespace(name="testhost", physical_core_count=lambda: cores)


def _banner(caplog, cfg: Config, caps: Capabilities, plat=None) -> dict[str, str]:
    with caplog.at_level(logging.INFO, logger="stenographer.lib.daemon"):
        _log_banner(cfg, _platform() if plat is None else plat, caps, _CONFIG_PATH)
    lines = [record.getMessage() for record in caplog.records]
    return {line.split()[1]: line for line in lines}


def test_overlay_backend_name_reports_disabled_available_unavailable_and_unknown():
    assert _overlay_backend_name(OverlayCapability.disabled()) == "disabled"
    assert _overlay_backend_name(OverlayCapability.available(Backend.XWAYLAND)) == "xwayland"
    assert (
        _overlay_backend_name(OverlayCapability.unavailable(UnavailableReason.NO_X_DISPLAY))
        == f"unavailable_{UnavailableReason.NO_X_DISPLAY.value}"
    )
    # Enabled with neither a backend nor a reason is a contradiction; it must
    # still render as a value rather than disappear from the line.
    assert _overlay_backend_name(OverlayCapability(True)) == "unknown"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "<unset>"),
        (True, 1),
        (False, 0),
        ((-60.0, -55.5), "-60,-55.5"),
        ("hw:1,0", "hw:1,0"),
        (0.35, 0.35),
    ],
)
def test_shown_renders_unset_bool_and_profile_values_visibly(value, expected):
    assert _shown(value) == expected


def test_banner_reports_build_backends_and_every_configured_key(caplog):
    from stenographer._version import __version__

    cfg = Config.defaults()
    lines = _banner(caplog, cfg, _capabilities())

    assert set(lines) == {
        "build",
        "backends",
        "config_hotkey",
        "config_audio",
        "config_asr",
        "config_feedback",
        "config_refine",
        "config_analytics",
    }
    assert f"version={__version__}" in lines["build"]
    assert "platform=testhost" in lines["build"]
    assert f"config={_CONFIG_PATH}" in lines["build"]
    assert "clipboard=wl-copy" in lines["backends"]
    assert "overlay=layer-shell" in lines["backends"]
    assert "cue_player=pulse" in lines["backends"]
    assert f"binding={cfg.hotkey.binding}" in lines["config_hotkey"]
    assert f"mode={cfg.hotkey.mode}" in lines["config_hotkey"]
    assert f"min_speech_rms={cfg.audio.min_speech_rms}" in lines["config_audio"]
    assert f"model={cfg.asr.model}" in lines["config_asr"]
    assert f"beam_size={cfg.asr.beam_size}" in lines["config_asr"]
    assert f"sound_pack={cfg.feedback.sound_pack}" in lines["config_feedback"]
    assert f"log_level={cfg.feedback.log_level}" in lines["config_feedback"]
    assert f"enabled={int(cfg.analytics.enabled)}" in lines["config_analytics"]


def test_banner_reports_unset_optionals_rather_than_dropping_their_keys(caplog):
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        hotkey=dataclasses.replace(defaults.hotkey, cancel_binding=None, device=None),
        audio=dataclasses.replace(defaults.audio, input_device=None),
        feedback=dataclasses.replace(defaults.feedback, spectrum_floor_dbfs=None),
    )
    caps = _capabilities(cue_player=None, overlay=OverlayCapability.disabled())

    lines = _banner(caplog, cfg, caps)

    assert "cancel_binding=<unset>" in lines["config_hotkey"]
    assert "device=<unset>" in lines["config_hotkey"]
    assert "input_device=<unset>" in lines["config_audio"]
    assert "spectrum_floor_dbfs=<unset>" in lines["config_feedback"]
    assert "cue_player=<unset>" in lines["backends"]
    assert "overlay=disabled" in lines["backends"]


def test_banner_reports_a_calibrated_profile_as_its_own_values(caplog):
    defaults = Config.defaults()
    profile = (-61.0, -60.5)
    cfg = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, spectrum_floor_dbfs=profile),
    )

    lines = _banner(caplog, cfg, _capabilities())

    assert "spectrum_floor_dbfs=-61,-60.5" in lines["config_feedback"]


def test_banner_reports_user_prose_only_as_sizes(caplog):
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        asr=dataclasses.replace(
            defaults.asr,
            hotwords="Kubernetes stenographer evdev",
            initial_prompt="A private note about my employer.",
        ),
    )

    lines = _banner(caplog, cfg, _capabilities())

    assert "hotwords_words=3" in lines["config_asr"]
    assert "initial_prompt_chars=33" in lines["config_asr"]
    for line in lines.values():
        assert "Kubernetes" not in line
        assert "employer" not in line


def test_banner_reports_the_resolved_thread_count_from_the_host_core_count(caplog):
    defaults = Config.defaults()
    cfg = dataclasses.replace(defaults, asr=dataclasses.replace(defaults.asr, cpu_threads=0))

    counted = _banner(caplog, cfg, _capabilities(), _platform(6))
    caplog.clear()
    uncounted = _banner(caplog, cfg, _capabilities(), _platform(None))

    assert "cpu_threads=0" in counted["config_asr"]
    assert "resolved_cpu_threads=6" in counted["config_asr"]
    assert "resolved_cpu_threads=4" in uncounted["config_asr"]


def test_banner_reports_the_refine_stage_and_marks_a_loopback_host_as_local(caplog):
    cfg = Config.defaults()

    lines = _banner(caplog, cfg, _capabilities())

    line = lines["config_refine"]
    assert f"enabled={int(cfg.refine.enabled)}" in line
    assert f"model={cfg.refine.model}" in line
    assert f"min_words={cfg.refine.min_words}" in line
    assert "host=127.0.0.1:11434" in line
    assert "loopback=1" in line
    assert "remote_host" not in "\n".join(lines)


def test_an_enabled_non_loopback_refine_host_is_warned_about_at_every_start(caplog):
    """The one configuration that sends transcripts off the machine. It is the
    user's own choice, so the daemon starts — but never quietly."""
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        refine=dataclasses.replace(defaults.refine, enabled=True, host="http://192.168.1.5:11434"),
    )

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.daemon"):
        lines = _banner(caplog, cfg, _capabilities())

    assert "loopback=0" in lines["config_refine"]
    assert "host=192.168.1.5:11434" in lines["config_refine"]
    warning = lines["remote_host"]
    assert "leaves_machine=1" in warning
    assert "host=192.168.1.5:11434" in warning


def test_a_disabled_stage_on_a_remote_host_is_reported_but_not_warned_about(caplog):
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        refine=dataclasses.replace(defaults.refine, enabled=False, host="http://192.168.1.5:11434"),
    )

    lines = _banner(caplog, cfg, _capabilities())

    assert "loopback=0" in lines["config_refine"]
    assert "remote_host" not in lines


def test_the_banner_never_echoes_credentials_written_into_the_refine_host(caplog):
    """Validation rejects userinfo, but the banner is written before anything
    else runs and must not be the place a secret first appears in the log."""
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        refine=dataclasses.replace(
            defaults.refine, enabled=True, host="http://user:hunter2@192.168.1.5:11434"
        ),
    )

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.daemon"):
        lines = _banner(caplog, cfg, _capabilities())

    rendered = "\n".join(lines.values())
    assert "hunter2" not in rendered
    assert "user" not in rendered
    assert "host=192.168.1.5:11434" in lines["config_refine"]
