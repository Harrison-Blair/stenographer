# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``with_config`` wrapper: rejected configuration never reaches a handler."""

from __future__ import annotations

import argparse
import pathlib

import pytest

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


def test_partial_old_hotkey_config_keeps_binding_as_agent_and_adds_general():
    cfg = Config.loads('[stenographer.hotkey]\nbinding = "KEY_F9"\n')
    assert cfg.hotkey.binding == "KEY_F9"
    assert cfg.hotkey.general_binding == "KEY_RIGHTALT"


def test_old_right_alt_binding_remains_agent_and_gets_a_safe_general_fallback():
    cfg = Config.loads('[stenographer.hotkey]\nbinding = "KEY_RIGHTALT"\n')
    assert cfg.hotkey.binding == "KEY_RIGHTALT"
    assert cfg.hotkey.general_binding == "KEY_RIGHTCTRL"


def test_old_partial_config_always_gets_a_non_overlapping_general_binding():
    cfg = Config.loads(
        "[stenographer.hotkey]\n"
        'binding = "KEY_RIGHTALT+KEY_F12"\n'
        'cancel_binding = "KEY_RIGHTCTRL"\n'
    )
    bindings = [
        set(value.split("+"))
        for value in (
            cfg.hotkey.binding,
            cfg.hotkey.general_binding,
            cfg.hotkey.cancel_binding,
        )
    ]
    assert all(
        not (left <= right or right <= left)
        for index, left in enumerate(bindings)
        for right in bindings[index + 1 :]
    )


@pytest.mark.parametrize(
    "content",
    [
        '[stenographer.hotkey]\nbinding = "KEY_RIGHTCTRL"\ngeneral_binding = "KEY_RIGHTCTRL"\n',
        '[stenographer.hotkey]\nbinding = "KEY_LEFTCTRL+KEY_A"\ngeneral_binding = "KEY_LEFTCTRL"\n',
        '[stenographer.hotkey]\nbinding = "KEY_ESC+KEY_A"\ncancel_binding = "KEY_ESC"\n',
    ],
)
def test_profile_and_cancel_bindings_must_not_be_equal_or_subsets(content):
    with pytest.raises(Exception, match="overlap"):
        Config.loads(content)
