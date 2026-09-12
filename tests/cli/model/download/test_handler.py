# SPDX-License-Identifier: GPL-3.0-or-later
"""``model download``: what it selects, what it says it will cost, and what it fetches."""

from __future__ import annotations

import argparse
import dataclasses

import pytest

from stenographer.cli.model.download.handler import (
    DECLINED_HINT,
    cmd_model_download,
    plan_lines,
    selection,
    size_phrase,
)
from stenographer.lib.config.models import Config


def test_download_fetches_the_configured_model_and_names_it(monkeypatch, capsys):
    from stenographer.lib.transcribe import download

    requested: list[str] = []
    monkeypatch.setattr(download, "download_model", requested.append)
    defaults = Config.defaults()
    cfg = dataclasses.replace(defaults, asr=dataclasses.replace(defaults.asr, model="small.en"))

    assert cmd_model_download.__wrapped__(argparse.Namespace(), cfg) == 0

    assert requested == ["small.en"]
    assert capsys.readouterr().out == "stenographer: downloaded small.en\n"


def test_a_failed_download_is_not_reported_as_a_success(monkeypatch, capsys):
    from stenographer.lib.transcribe import download

    class UnreachableError(RuntimeError):
        pass

    def fail(model_id):
        raise UnreachableError("no route to host")

    monkeypatch.setattr(download, "download_model", fail)

    with pytest.raises(UnreachableError):
        cmd_model_download.__wrapped__(argparse.Namespace(), Config.defaults())

    assert capsys.readouterr().out == ""


def test_neither_flag_without_a_terminal_keeps_the_historical_asr_only_behavior():
    """An existing script that ran `stenographer model download` must not
    silently start a second multi-gigabyte pull it never asked for."""
    assert selection(argparse.Namespace(), interactive=False) == (True, False)
    assert selection(argparse.Namespace(asr=False, refine=False), interactive=True) == (True, True)


@pytest.mark.parametrize(
    ("asr", "refine", "expected"),
    [(True, False, (True, False)), (False, True, (False, True)), (True, True, (True, True))],
)
def test_an_explicit_flag_selects_only_what_it_names(asr, refine, expected):
    args = argparse.Namespace(asr=asr, refine=refine)

    assert selection(args, interactive=True) == expected
    assert selection(args, interactive=False) == expected


def test_an_installed_model_is_reported_at_its_real_size_not_the_table():
    assert size_phrase("m", 3_389_983_735, 9.9) == "already installed, 3.4 GB"


def test_a_known_model_is_sized_from_the_table_before_it_exists_locally():
    assert size_phrase("m", None, 3.4) == "about 3.4 GB"


def test_an_unknown_model_is_never_guessed_at():
    assert size_phrase("someone/custom:tag", None, None) == "size unknown"


def _plan_cfg():
    defaults = Config.defaults()
    return dataclasses.replace(
        defaults,
        asr=dataclasses.replace(defaults.asr, model="small.en"),
        refine=dataclasses.replace(defaults.refine, model="some:tag"),
    )


def test_the_confirmation_states_both_models_their_sizes_and_the_host():
    cfg = _plan_cfg()

    lines = plan_lines(cfg, asr=True, refine=True, refine_size="about 3.4 GB")

    assert lines == [
        "download the ASR model small.en (about 1.6 GB)",
        "download the refine model some:tag (about 3.4 GB) via http://127.0.0.1:11434",
    ]
    assert plan_lines(cfg, asr=True, refine=False, refine_size=None) == lines[:1]


def test_a_refine_model_ollama_already_has_is_not_announced_as_a_download():
    """Claiming a multi-gigabyte download is about to start when it is not is
    how a confirm prompt stops being read."""
    lines = plan_lines(
        _plan_cfg(),
        asr=False,
        refine=True,
        refine_size=size_phrase("some:tag", 3_400_000_000, None),
    )

    assert lines == [
        "verify the refine model some:tag (already installed, 3.4 GB) via http://127.0.0.1:11434"
    ]
    assert "download" not in lines[0]


def test_a_refine_pull_that_ollama_refuses_is_not_reported_as_a_success(monkeypatch, capsys):
    from stenographer.lib.refine import client
    from stenographer.lib.refine.errors import RefineTransportError

    def refuse(host, model, *, on_progress=None, timeout=None):
        raise RefineTransportError("ollama could not be reached")

    monkeypatch.setattr(client, "pull_model", refuse)

    assert (
        cmd_model_download.__wrapped__(
            argparse.Namespace(asr=False, refine=True), Config.defaults()
        )
        == 1
    )

    captured = capsys.readouterr()
    assert "could not pull" in captured.err
    assert captured.out == ""


def test_declining_the_combined_offer_names_the_flag_for_fetching_only_one():
    """Saying no to both must not be a dead end for someone who wanted one."""
    assert "--asr" in DECLINED_HINT
    assert "--refine" in DECLINED_HINT
