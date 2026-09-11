# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``with_config`` wrapper: rejected configuration never reaches a handler."""

from __future__ import annotations

import argparse
import pathlib

from stenographer.cli.shared.config import with_config
from stenographer.lib.config.errors import ConfigError
from stenographer.lib.config.models import Config


def test_rejected_configuration_is_reported_verbatim_and_never_reaches_the_handler(
    monkeypatch,
    capsys,
):
    from stenographer.lib.config import paths
    from stenographer.lib.logging import pipeline as logging_pipeline

    calls: list[str] = []

    def refuse() -> Config:
        raise ConfigError(
            pathlib.PurePosixPath("/cfg/config.toml"),
            "asr.beam_size",
            "must be 1-10",
        )

    monkeypatch.setattr(paths, "load_or_default", refuse)
    monkeypatch.setattr(logging_pipeline, "apply_stderr_level", lambda level: calls.append(level))

    @with_config
    def handler(args, cfg):
        calls.append("handler")
        return 0

    assert handler(argparse.Namespace()) == 78
    assert calls == []
    assert capsys.readouterr().err == (
        "stenographer: /cfg/config.toml: asr.beam_size: must be 1-10\n"
    )


def test_a_loaded_configuration_sets_the_stderr_threshold_before_the_handler_runs(
    monkeypatch,
    capsys,
):
    from stenographer.lib.config import paths
    from stenographer.lib.logging import pipeline as logging_pipeline

    events: list[str] = []
    cfg = Config.defaults()

    monkeypatch.setattr(paths, "load_or_default", lambda: cfg)
    monkeypatch.setattr(
        logging_pipeline,
        "apply_stderr_level",
        lambda level: events.append(f"level:{level}"),
    )

    @with_config
    def handler(args, loaded):
        events.append("handler")
        assert loaded is cfg
        return 3

    assert handler(argparse.Namespace()) == 3
    assert events == [f"level:{cfg.feedback.log_level}", "handler"]
    assert capsys.readouterr().err == ""
