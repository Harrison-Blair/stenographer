# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the prompt-mode cue-remapping adapter in :mod:`stenographer.cli`."""

from __future__ import annotations

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


def test_dictate_listener_uses_unmapped_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _FakeHotkeyListener:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self) -> None:
            pass

        def stop(self, timeout: float = 2.0) -> None:
            pass

    monkeypatch.setattr(cli, "HotkeyListener", _FakeHotkeyListener)

    cfg = Config.defaults()
    caps = Capabilities(
        has_wtype=False,
        has_wl_copy=False,
        has_pw_play=False,
        has_paplay=False,
        has_input_group=False,
        has_mic=False,
        has_asr_model=False,
    )

    session = cli._build_session(cfg, caps, one_shot=False)
    try:
        assert len(calls) == 2
        dictate_feedback = calls[0]["feedback"]
        prompt_feedback = calls[1]["feedback"]
        assert isinstance(dictate_feedback, Feedback)
        assert not isinstance(prompt_feedback, Feedback)
        assert prompt_feedback is not dictate_feedback
    finally:
        session.stop()
