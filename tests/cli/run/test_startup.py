# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-gated startup policy."""

from __future__ import annotations

import dataclasses
import pathlib
from types import SimpleNamespace

from stenographer.cli.run import startup
from stenographer.cli.run.startup import run
from stenographer.cli.shared.capabilities import REQUIRED, missing_required
from stenographer.lib.config.models import Config
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.updates import notice
from stenographer.overlay.capabilities.models import OverlayCapability
from tests.cli.support import capabilities
from tests.lib.daemon.support import _daemon


def _startup_caps(**overrides):
    return capabilities(**({"overlay": OverlayCapability.disabled()} | overrides))


def test_startup_gate_tracks_every_current_doctor_requirement(monkeypatch, capsys):
    from stenographer.cli.run import startup
    from stenographer.cli.shared import capabilities as capability_probe

    monkeypatch.setattr(startup, "_log_banner", lambda *args: None)
    for name in REQUIRED:
        caps = dataclasses.replace(_startup_caps(), **{name: False})
        monkeypatch.setattr(capability_probe, "probe", lambda cfg, caps=caps: caps)
        assert run(Config.defaults()) == 78, name
        assert "required capabilities unavailable" in capsys.readouterr().err


def test_startup_gate_ignores_optional_capabilities_and_reuses_backend():
    caps = _startup_caps(
        clipboard_backend="x11",
        cue_player=None,
        service_enabled=None,
        service_active=None,
        overlay=OverlayCapability.disabled(),
    )
    assert not missing_required(caps)
    assert caps.clipboard_backend == "x11"


def test_run_prepares_the_recorder_and_hands_the_notifier_to_the_update_check(
    monkeypatch,
    tmp_path,
):
    # A real Daemon: both steps sit behind handlers that only log a failure, so
    # a wrong accessor would otherwise leave startup looking healthy.
    daemon = _daemon()
    prepared: list[bool] = []
    daemon._recorder.prepare = lambda: prepared.append(True)
    daemon.run = lambda: None
    checks: list[tuple] = []
    host = SimpleNamespace(
        single_instance_lock=lambda: SimpleNamespace(acquire=lambda: True, release=lambda: None),
        install_stop_handlers=lambda handler: None,
        state_dir=lambda env, home: pathlib.Path(tmp_path),
        name="test",
        physical_core_count=lambda: 2,
    )
    monkeypatch.setattr(startup, "current_platform", lambda: host)
    monkeypatch.setattr("stenographer.cli.shared.capabilities.probe", lambda _cfg: _startup_caps())
    monkeypatch.setattr(Daemon, "build", classmethod(lambda cls, *args, **kwargs: daemon))
    monkeypatch.setattr(notice, "start_background_check", lambda *args: checks.append(args))
    defaults = Config.defaults()
    cfg = dataclasses.replace(
        defaults,
        feedback=dataclasses.replace(defaults.feedback, overlay=False, update_check=True),
    )

    assert startup.run(cfg) == 0

    assert prepared == [True]
    assert [check[2] for check in checks] == [daemon._notifier]
