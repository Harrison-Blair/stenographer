# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :mod:`stenographer.cli`."""

from __future__ import annotations

import logging
import pathlib
from dataclasses import replace
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

import stenographer.cli as cli
from stenographer.asr.model import SegmentInfo, TranscriptionResult
from stenographer.audio.feedback import Feedback
from stenographer.capabilities import Capabilities
from stenographer.config import Config


def test_cli_has_no_prompt_cue_adapter() -> None:
    assert hasattr(cli, "_PromptCueAdapter") is False


def _caps() -> Capabilities:
    return Capabilities(
        has_paste_trigger=False,
        has_wl_copy=False,
        has_pw_play=False,
        has_paplay=False,
        has_input_group=False,
        has_mic=False,
        has_asr_model=False,
    )


class _FakeHotkeyListener:
    calls: ClassVar[list[dict]] = []

    def __init__(self, **kwargs):
        type(self).calls.append(kwargs)

    def start(self) -> None:
        pass

    def stop(self, timeout: float = 2.0) -> None:
        pass


def test_dictate_listener_uses_unmapped_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "HotkeyListener", _FakeHotkeyListener)
    monkeypatch.setattr(_FakeHotkeyListener, "calls", [])
    calls = _FakeHotkeyListener.calls

    session = cli._build_session(Config.defaults(), _caps(), one_shot=False)
    try:
        assert len(calls) == 1
        dictate_feedback = calls[0]["feedback"]
        assert isinstance(dictate_feedback, Feedback)
    finally:
        session.stop()


def test_run_stop_names_stop_replacement(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["run", "stop"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "stenographer stop" in captured.err
    assert "unrecognized arguments" not in captured.err


def test_run_disable_names_disable_replacement(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["run", "disable"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "stenographer disable" in captured.err
    assert "unrecognized arguments" not in captured.err


def test_run_alone_still_dispatches_normally() -> None:
    from stenographer._parser import build_parser

    args = build_parser().parse_args(["run"])
    assert args.subcommand == "run"


def test_startup_update_check_disabled_does_not_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config.defaults()
    cfg = replace(cfg, update=replace(cfg.update, check_on_startup=False))
    notification = MagicMock()
    monkeypatch.setattr(
        cli,
        "_check_for_update_on_startup",
        lambda _cfg, _notification: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert cli._start_update_check(cfg, notification) is None


def test_startup_update_check_launches_daemon_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[Config, object]] = []
    monkeypatch.setattr(
        cli,
        "_check_for_update_on_startup",
        lambda cfg, notification: called.append((cfg, notification)),
    )
    defaults = Config.defaults()
    cfg = replace(defaults, update=replace(defaults.update, check_on_startup=True))
    notification = MagicMock()
    thread = cli._start_update_check(cfg, notification)
    assert thread is not None
    thread.join(timeout=1)
    assert called == [(cfg, notification)]
    assert thread.daemon is True
    assert thread.name == "startup-update-check"


def test_startup_update_check_notifies_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    notification = MagicMock()
    info = MagicMock(latest_version="0.9.3")
    monkeypatch.setattr(cli, "check_for_update", lambda _cfg: info)

    cli._check_for_update_on_startup(Config.defaults(), notification)

    notification.show_update_available.assert_called_once_with("0.9.3")


def test_startup_update_check_current_does_not_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "check_for_update", lambda _cfg: None)
    notification = MagicMock()

    cli._check_for_update_on_startup(Config.defaults(), notification)

    notification.show_update_available.assert_not_called()


def test_startup_update_check_network_failure_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from stenographer.errors import UpdateError

    def _fail(_cfg: object) -> None:
        raise UpdateError("update: network unavailable")

    monkeypatch.setattr(cli, "check_for_update", _fail)
    notification = MagicMock()
    with caplog.at_level(logging.WARNING):
        cli._check_for_update_on_startup(Config.defaults(), notification)
    assert "startup update check failed" in caplog.text
    assert "network unavailable" in caplog.text


def test_run_launches_update_check_after_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _Probe:
        @staticmethod
        def probe(_cfg: Config) -> Capabilities:
            return Capabilities(True, True, True, True, True, True, True)

    session = MagicMock()
    session.notification.show_startup.side_effect = lambda _binding: events.append("ready")
    session.run.side_effect = lambda: events.append("run")
    monkeypatch.setattr(cli, "Capabilities", _Probe)
    monkeypatch.setattr(cli, "_acquire_single_instance_lock", lambda: 0)
    monkeypatch.setattr(cli, "_build_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda _session: None)
    monkeypatch.setattr(cli, "_release_single_instance_lock", lambda: None)
    monkeypatch.setattr(
        cli,
        "_start_update_check",
        lambda _cfg, _notification: events.append("check"),
    )

    assert cli.cmd_run(Config.defaults()) == 0
    assert events == ["ready", "check", "run"]


def _transcribe_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="i think so",
        duration_seconds=1.0,
        segments=[SegmentInfo(start=0.0, end=1.0, text=" i think so", no_speech_prob=0.0)],
    )


class _FakeTranscribeModel:
    def __init__(self, cfg: object) -> None:
        pass

    def transcribe(self, samples: object, language: object, beam_size: object) -> object:
        return _transcribe_result()


def _patch_transcribe_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "Capabilities", _StubCapabilitiesProbe)
    monkeypatch.setattr(cli, "Model", _FakeTranscribeModel)
    monkeypatch.setattr(
        cli.soundfile,
        "read",
        lambda path, dtype, always_2d: (b"", Config.defaults().audio.sample_rate),
    )


class _StubCapabilitiesProbe:
    @staticmethod
    def probe(cfg: object) -> Capabilities:
        return Capabilities(
            has_paste_trigger=False,
            has_wl_copy=False,
            has_pw_play=False,
            has_paplay=False,
            has_input_group=False,
            has_mic=False,
            has_asr_model=True,
        )


def test_transcribe_default_output_is_formatted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    _patch_transcribe_deps(monkeypatch)
    path = tmp_path / "clip.wav"
    path.write_bytes(b"")

    rc = cli.cmd_transcribe(Config.defaults(), path, raw=False)

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "I think so \n"


def test_transcribe_raw_flag_emits_verbatim_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    _patch_transcribe_deps(monkeypatch)
    path = tmp_path / "clip.wav"
    path.write_bytes(b"")

    rc = cli.cmd_transcribe(Config.defaults(), path, raw=True)

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "i think so\n"


def test_parser_accepts_transcribe_raw_flag() -> None:
    from stenographer._parser import build_parser

    with_flag = build_parser().parse_args(["transcribe", "f.wav", "--raw"])
    without_flag = build_parser().parse_args(["transcribe", "f.wav"])
    assert with_flag.raw is True
    assert without_flag.raw is False
