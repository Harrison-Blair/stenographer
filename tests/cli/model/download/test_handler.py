# SPDX-License-Identifier: GPL-3.0-or-later
"""``model download``: what it selects, what it says it will cost, and what it fetches."""

from __future__ import annotations

import argparse
import dataclasses
import io

import pytest

from stenographer.cli.model.download.handler import (
    cmd_model_download,
    size_phrase,
)
from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config
from tests.cli.support import Terminal as _Terminal


@pytest.fixture
def asr_seams(monkeypatch, tmp_path):
    """Fake the Bark build; record what it was asked to do."""
    from stenographer.lib.transcribe import bark_download

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    calls: list[str] = []
    state = {"built": True, "error": None}

    def build(data_dir, *, on_step):
        calls.append(f"bark:{data_dir}")
        on_step("converting to int8 ONNX (several minutes)")
        if state["error"] is not None:
            raise state["error"]
        return state["built"]

    monkeypatch.setattr(bark_download, "download_bark_pro", build)
    return calls, state, tmp_path / "stenographer"


def test_asr_builds_bark_pro_and_prints_the_attribution(asr_seams, capsys):
    calls, _, data_dir = asr_seams

    result = cmd_model_download.__wrapped__(
        argparse.Namespace(asr=True, refine=False), Config.defaults()
    )

    assert result == 0
    assert calls == [f"bark:{data_dir}"]
    out = capsys.readouterr().out
    assert out == (
        "stenographer: converting to int8 ONNX (several minutes)\n"
        f"stenographer: ASR model installed at {data_dir}/models/asr/bark-pro-int8\n"
        "stenographer: Underdog Bark 3.0 Pro by Conway Research (CC BY 4.0), "
        "converted to int8 ONNX on this machine\n"
    )


def test_asr_reports_a_present_model_without_rebuilding_claims(asr_seams, capsys):
    _, state, _ = asr_seams
    state["built"] = False

    assert (
        cmd_model_download.__wrapped__(
            argparse.Namespace(asr=False, refine=False), Config.defaults()
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "ASR model already present at" in out


def test_a_failed_asr_build_is_not_reported_as_a_success(asr_seams, capsys):
    from stenographer.lib.transcribe.errors import BarkDownloadError

    _, state, _ = asr_seams
    state["error"] = BarkDownloadError("Free-space check failed: free some disk space")

    assert (
        cmd_model_download.__wrapped__(
            argparse.Namespace(asr=False, refine=False), Config.defaults()
        )
        == 1
    )

    captured = capsys.readouterr()
    assert captured.err == (
        "stenographer: could not install the ASR model: "
        "Free-space check failed: free some disk space\n"
    )
    assert "installed at" not in captured.out


@pytest.mark.parametrize(
    ("asr", "refine", "interactive", "enabled", "expected"),
    [
        (False, False, False, True, ["asr"]),
        (False, False, True, False, ["asr"]),
        (False, False, True, True, ["asr", "refine"]),
        (True, False, True, True, ["asr"]),
        (False, True, False, False, ["refine"]),
        (True, True, True, True, ["asr", "refine"]),
    ],
)
def test_selection_at_command_level(monkeypatch, asr, refine, interactive, enabled, expected):
    from stenographer.cli.model.download import handler
    from stenographer.cli.shared import terminal
    from stenographer.lib.refine import client

    calls = []
    monkeypatch.setattr(handler, "_download_asr", lambda: calls.append("asr") or 0)
    monkeypatch.setattr(handler, "_pull_refine", lambda cfg: calls.append("refine") or 0)
    monkeypatch.setattr(client, "installed_model_bytes", lambda *args: None)
    monkeypatch.setattr(terminal, "ask_yes_no", lambda *args, **kwargs: True)
    stream = _Terminal() if interactive else io.StringIO()
    monkeypatch.setattr(terminal, "open_console", lambda *_: Console(stream, stream, io.StringIO()))
    cfg = Config.defaults()
    cfg = dataclasses.replace(cfg, refine=dataclasses.replace(cfg.refine, enabled=enabled))
    assert cmd_model_download.__wrapped__(argparse.Namespace(asr=asr, refine=refine), cfg) == 0
    assert calls == expected


@pytest.mark.parametrize(
    ("installed", "approximate", "expected"),
    [
        (3_389_983_735, 9.9, "already installed, 3.4 GB"),
        (None, 3.4, "about 3.4 GB"),
        (None, None, "size unknown"),
    ],
)
def test_size_phrase(installed, approximate, expected):
    assert size_phrase(installed, approximate) == expected


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (None, "download the refine model some:tag (size unknown)"),
        (3_400_000_000, "verify the refine model some:tag (already installed, 3.4 GB)"),
    ],
)
def test_confirmation_plan(monkeypatch, installed, expected):
    from stenographer.cli.shared import terminal
    from stenographer.lib.refine import client

    monkeypatch.setattr(client, "installed_model_bytes", lambda *args: installed)
    console = Console(_Terminal("\n"), _Terminal(), io.StringIO())
    monkeypatch.setattr(terminal, "open_console", lambda *_: console)
    cfg = Config.defaults()
    cfg = dataclasses.replace(cfg, refine=dataclasses.replace(cfg.refine, model="some:tag"))
    assert cmd_model_download.__wrapped__(argparse.Namespace(asr=False, refine=False), cfg) == 0
    output = console.stdout.getvalue()
    assert (
        "download and convert the ASR model Underdog Bark 3.0 Pro "
        "(about 1.6 GB download, 10 GiB free disk while it converts)" in output
    )
    assert expected + " via http://127.0.0.1:11434" in output


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


def test_a_stray_enter_declines_the_combined_offer_instead_of_starting_it(monkeypatch):
    """A user refreshing only the ASR model who presses Enter without reading
    the prompt must not start an unwanted multi-gigabyte refine pull: the
    confirmation now defaults to declining, not accepting."""
    from stenographer.cli.shared import terminal
    from stenographer.lib.refine import client
    from stenographer.lib.transcribe import bark_download

    asr_calls: list[object] = []
    refine_calls: list[str] = []
    monkeypatch.setattr(bark_download, "download_bark_pro", lambda *a, **kw: asr_calls.append(a))
    monkeypatch.setattr(client, "pull_model", lambda host, model, **kw: refine_calls.append(model))
    monkeypatch.setattr(client, "installed_model_bytes", lambda host, model: None)

    console = Console(_Terminal("\n"), _Terminal(), io.StringIO())
    monkeypatch.setattr(terminal, "open_console", lambda *_: console)

    result = cmd_model_download.__wrapped__(
        argparse.Namespace(asr=False, refine=False), Config.defaults()
    )

    assert result == 0
    assert asr_calls == []
    assert refine_calls == []
    assert "Nothing was downloaded." in console.stdout.getvalue()
    assert "--asr" in console.stdout.getvalue()
    assert "--refine" in console.stdout.getvalue()
