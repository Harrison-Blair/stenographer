# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the prompt-mode cue-remapping adapter in :mod:`stenographer.cli`."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import pytest

import stenographer.cli as cli
from stenographer.audio.feedback import Feedback
from stenographer.capabilities import Capabilities
from stenographer.config import Config


def test_prompt_cue_adapter_remaps_start_stop_cues() -> None:
    underlying = MagicMock()
    adapter = cli._PromptCueAdapter(underlying)

    adapter.play("ptt_on")
    adapter.play("toggle_on")
    adapter.play("ptt_off")
    adapter.play("toggle_off")

    assert underlying.play.call_args_list == [
        (("ptt_on_prompt",), {}),
        (("toggle_on_prompt",), {}),
        (("ptt_off_prompt",), {}),
        (("toggle_off_prompt",), {}),
    ]


@pytest.mark.parametrize(
    "cue_name", ["cancel", "discard", "error", "segment", "transcribe_done", "model_loading"]
)
def test_prompt_cue_adapter_passes_through_other_cues_unchanged(cue_name: str) -> None:
    underlying = MagicMock()
    adapter = cli._PromptCueAdapter(underlying)

    adapter.play(cue_name)

    underlying.play.assert_called_once_with(cue_name)


def _caps() -> Capabilities:
    return Capabilities(
        has_wtype=False,
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
        assert len(calls) == 2
        dictate_feedback = calls[0]["feedback"]
        prompt_feedback = calls[1]["feedback"]
        assert isinstance(dictate_feedback, Feedback)
        assert not isinstance(prompt_feedback, Feedback)
        assert prompt_feedback is not dictate_feedback
    finally:
        session.stop()


def test_prompt_listener_discard_is_source_tagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "HotkeyListener", _FakeHotkeyListener)
    monkeypatch.setattr(_FakeHotkeyListener, "calls", [])
    calls = _FakeHotkeyListener.calls

    session = cli._build_session(Config.defaults(), _caps(), one_shot=False)
    try:
        prompt_discard = calls[1]["on_discard"]
        assert prompt_discard.keywords == {"source": "prompt"}
    finally:
        session.stop()


def test_empty_prompt_binding_disables_prompt_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    monkeypatch.setattr(cli, "HotkeyListener", _FakeHotkeyListener)
    monkeypatch.setattr(_FakeHotkeyListener, "calls", [])
    calls = _FakeHotkeyListener.calls

    cfg = Config.defaults()
    cfg = replace(cfg, hotkey=replace(cfg.hotkey, prompt_binding=""))

    session = cli._build_session(cfg, _caps(), one_shot=False)
    try:
        assert len(calls) == 1
        assert session._prompt_listener is None
    finally:
        session.stop()
