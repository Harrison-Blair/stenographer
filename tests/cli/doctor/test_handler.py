# SPDX-License-Identifier: GPL-3.0-or-later
"""``doctor`` dispatch: the loaded config and its resolved path reach the report."""

from __future__ import annotations

import argparse

from stenographer.cli.doctor.handler import cmd_doctor
from stenographer.lib.config.models import Config


def test_doctor_hands_the_report_the_loaded_config_and_its_resolved_path(
    monkeypatch,
    tmp_path,
):
    from stenographer.cli.doctor import report as doctor
    from stenographer.lib.config import paths
    from stenographer.lib.logging import pipeline as logging_pipeline

    path = tmp_path / "cfg" / "config.toml"
    monkeypatch.setenv("STENOGRAPHER_CONFIG", str(path))
    cfg = Config.defaults()
    monkeypatch.setattr(paths, "load_or_default", lambda: cfg)
    monkeypatch.setattr(logging_pipeline, "apply_stderr_level", lambda level: None)

    seen: list[object] = []

    def report(config, config_path):
        seen.append((config, config_path))
        return 78

    monkeypatch.setattr(doctor, "run", report)

    assert cmd_doctor(argparse.Namespace()) == 78
    assert seen == [(cfg, path)]
    # @with_config resolves the path with create_parent=True, so doctor can name
    # a directory the user has not created yet.
    assert path.parent.is_dir()
