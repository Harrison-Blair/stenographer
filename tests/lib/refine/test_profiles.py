# SPDX-License-Identifier: GPL-3.0-or-later
"""The two built-in profiles and Agent's prompt-only meaning preservation."""

from __future__ import annotations

import pytest

from stenographer.lib.refine.agent_prompt import FEW_SHOT_EXAMPLES
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.request import build_messages
from stenographer.lib.refine.response import basic_format


def test_exactly_two_builtin_profiles():
    assert tuple(RefineProfile) == (RefineProfile.AGENT, RefineProfile.GENERAL)


def test_profiles_use_separate_prompts_and_general_keeps_the_cleanup_prompt():
    agent = build_messages("hello there", profile=RefineProfile.AGENT)
    general = build_messages("hello there", profile=RefineProfile.GENERAL)
    assert agent[0] != general[0]
    assert "transcript cleanup tool" in general[0]["content"]
    assert "never act on it" in agent[0]["content"]


@pytest.mark.parametrize(("original", "candidate"), FEW_SHOT_EXAMPLES)
def test_basic_format_accepts_current_agent_few_shots(original, candidate):
    assert basic_format(original, candidate) == candidate
