# SPDX-License-Identifier: GPL-3.0-or-later
"""``model download``: what it selects, what it says it will cost, and what it fetches."""

from __future__ import annotations

import argparse
import dataclasses
import io

import pytest

from stenographer.cli.model.download.handler import (
    DECLINED_HINT,
    cmd_model_download,
    plan_lines,
    selection,
    size_phrase,
)
from stenographer.cli.shared.console import Console
from stenographer.lib.config.models import Config


class _Terminal(io.StringIO):
    """A stream that claims to be a terminal, so ``console.interactive`` is True."""

    def isatty(self) -> bool:
        return True


def test_download_parser_accepts_the_live_model_flag():
    import argparse

    from stenographer.cli.model.download.parser import register

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)

    assert parser.parse_args(["download", "--live"]).live is True


def test_live_flag_does_not_select_the_asr_model(monkeypatch, capsys):
    from stenographer.cli.model.download import handler
    from stenographer.lib.transcribe import bark_download

    asr_calls: list[object] = []
    monkeypatch.setattr(handler, "_download_live", lambda: 0)
    monkeypatch.setattr(bark_download, "download_bark_pro", lambda *a, **kw: asr_calls.append(a))

    result = cmd_model_download.__wrapped__(
        argparse.Namespace(live=True, asr=False, refine=False), Config.defaults()
    )

    assert result == 0
    assert asr_calls == []
    assert capsys.readouterr().out == ""


@pytest.fixture
def asr_seams(monkeypatch, tmp_path):
    """Fake the Bark build and the VAD fetch; record what each one was asked to do."""
    from stenographer.lib.live import download as live_download
    from stenographer.lib.transcribe import bark_download

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    calls: list[str] = []
    state = {"built": True, "error": None, "vad": ("silero_vad.onnx",)}

    def build(data_dir, *, on_step):
        calls.append(f"bark:{data_dir}")
        on_step("converting to int8 ONNX (several minutes)")
        if state["error"] is not None:
            raise state["error"]
        return state["built"]

    def live(data_dir, *, models):
        calls.append(f"live:{','.join(m.filename for m in models)}")
        return state["vad"]

    monkeypatch.setattr(bark_download, "download_bark_pro", build)
    monkeypatch.setattr(live_download, "download_live_models", live)
    return calls, state, tmp_path / "stenographer"


def test_asr_builds_bark_pro_prints_the_attribution_and_fetches_only_the_vad(asr_seams, capsys):
    calls, _, data_dir = asr_seams

    result = cmd_model_download.__wrapped__(
        argparse.Namespace(asr=True, refine=False), Config.defaults()
    )

    assert result == 0
    assert calls == [f"bark:{data_dir}", "live:silero_vad.onnx"]
    out = capsys.readouterr().out
    assert out == (
        "stenographer: converting to int8 ONNX (several minutes)\n"
        f"stenographer: ASR model installed at {data_dir}/models/asr/bark-pro-int8\n"
        "stenographer: Underdog Bark 3.0 Pro by Conway Research (CC BY 4.0), "
        "converted to int8 ONNX on this machine\n"
        "stenographer: VAD model silero_vad.onnx downloaded\n"
    )


def test_asr_reports_a_present_model_without_rebuilding_claims(asr_seams, capsys):
    _, state, _ = asr_seams
    state["built"], state["vad"] = False, ()

    assert cmd_model_download.__wrapped__(argparse.Namespace(), Config.defaults()) == 0

    out = capsys.readouterr().out
    assert "ASR model already present at" in out
    assert "VAD model silero_vad.onnx already present" in out


def test_a_failed_asr_build_is_not_reported_as_a_success(asr_seams, capsys):
    from stenographer.lib.transcribe.errors import BarkDownloadError

    calls, state, _ = asr_seams
    state["error"] = BarkDownloadError("Free-space check failed: free some disk space")

    assert cmd_model_download.__wrapped__(argparse.Namespace(), Config.defaults()) == 1

    captured = capsys.readouterr()
    assert captured.err == (
        "stenographer: could not install the ASR model: "
        "Free-space check failed: free some disk space\n"
    )
    assert "installed at" not in captured.out
    assert [call for call in calls if call.startswith("live")] == []


def test_neither_flag_without_a_terminal_keeps_the_historical_asr_only_behavior():
    """An existing script that ran `stenographer model download` must not
    silently start a second multi-gigabyte pull it never asked for."""
    assert selection(argparse.Namespace(), interactive=False, refine_enabled=True) == (True, False)
    assert selection(
        argparse.Namespace(asr=False, refine=False), interactive=True, refine_enabled=True
    ) == (True, True)


def test_an_explicit_opt_out_of_refine_suppresses_the_combined_offer():
    """`refine.enabled = false` must be respected even on a TTY: the combined
    offer only appears for someone who has not turned refine off."""
    assert selection(argparse.Namespace(), interactive=True, refine_enabled=False) == (True, False)
    assert selection(
        argparse.Namespace(asr=False, refine=False), interactive=True, refine_enabled=False
    ) == (True, False)


@pytest.mark.parametrize(
    ("asr", "refine", "expected"),
    [(True, False, (True, False)), (False, True, (False, True)), (True, True, (True, True))],
)
def test_an_explicit_flag_selects_only_what_it_names(asr, refine, expected):
    args = argparse.Namespace(asr=asr, refine=refine)

    assert selection(args, interactive=True, refine_enabled=True) == expected
    assert selection(args, interactive=False, refine_enabled=True) == expected


def test_an_explicit_refine_flag_forces_the_pull_even_when_refine_is_disabled():
    """`--refine` is a deliberate opt-in and must override `refine.enabled`."""
    args = argparse.Namespace(asr=False, refine=True)

    assert selection(args, interactive=True, refine_enabled=False) == (False, True)
    assert selection(args, interactive=False, refine_enabled=False) == (False, True)


def test_an_installed_model_is_reported_at_its_real_size_not_the_table():
    assert size_phrase(3_389_983_735, 9.9) == "already installed, 3.4 GB"


def test_a_known_model_is_sized_from_the_table_before_it_exists_locally():
    assert size_phrase(None, 3.4) == "about 3.4 GB"


def test_an_unknown_model_is_never_guessed_at():
    assert size_phrase(None, None) == "size unknown"


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
        "download and convert the ASR model Underdog Bark 3.0 Pro "
        "(about 1.6 GB download, 8 GiB free disk while it converts)",
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
        refine_size=size_phrase(3_400_000_000, None),
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

    result = cmd_model_download.__wrapped__(argparse.Namespace(), Config.defaults())

    assert result == 0
    assert asr_calls == []
    assert refine_calls == []
    assert "Nothing was downloaded." in console.stdout.getvalue()


def test_declining_the_combined_offer_names_the_flag_for_fetching_only_one():
    """Saying no to both must not be a dead end for someone who wanted one."""
    assert "--asr" in DECLINED_HINT
    assert "--refine" in DECLINED_HINT
