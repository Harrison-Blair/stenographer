# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure maintenance races, wire validation and private configuration comparison."""

from dataclasses import replace

import pytest

from stenographer.config import AnalyticsConfig, Config, ConfigError
from stenographer.control import Maintenance, config_fingerprint, valid_request


def test_disconnection_releases_only_own_lease_and_never_service_reservation():
    state = Maintenance()
    assert not state.begin("one", "calibration", busy=True)
    assert state.begin("one", "calibration", busy=False)
    assert not state.begin("two", "shortcut", busy=False)
    assert not state.reserve("restart", busy=False)
    assert not state.release("two")
    assert state.occupied
    assert state.release("one")
    assert state.reserve("restart", busy=False)
    assert not state.release("one")
    assert state.occupied
    assert not state.begin("two", "sound", busy=False)


def test_control_rejects_versions_types_and_unknown_actions():
    request = {"version": 1, "id": "request", "action": "status", "payload": {}}
    assert valid_request(request)
    for update in (
        {"version": True},
        {"version": 2},
        {"id": ""},
        {"action": "dictate"},
        {"payload": []},
        {"transcript": "private"},
    ):
        assert not valid_request({**request, **update})


def test_analytics_settings_default_without_rewriting_old_files(tmp_path):
    path = tmp_path / "config.toml"
    content = "[stenographer.feedback]\nmute = true # preserved\n"
    path.write_text(content)
    cfg = Config.load(path)
    assert cfg.analytics == AnalyticsConfig(True, True)
    assert path.read_text() == content
    assert config_fingerprint(cfg) != config_fingerprint(
        replace(cfg, analytics=AnalyticsConfig(False))
    )
    assert len(config_fingerprint(cfg)) == 64
    for key in ("enabled", "resource_profiling"):
        with pytest.raises(ConfigError) as error:
            Config.loads(f'[stenographer.analytics]\n{key} = "true"')
        assert error.value.key == f"analytics.{key}"
