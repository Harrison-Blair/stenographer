# SPDX-License-Identifier: GPL-3.0-or-later
"""The two built-in profiles and Agent's prompt-only meaning preservation."""

from __future__ import annotations

import pytest

from stenographer.lib.refine.agent_prompt import FEW_SHOT_EXAMPLES
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.request import build_messages
from stenographer.lib.refine.response import basic_format


def test_exactly_two_builtin_profiles_with_agent_as_default():
    assert tuple(RefineProfile) == (RefineProfile.AGENT, RefineProfile.GENERAL)
    assert RefineProfile.default() is RefineProfile.AGENT


def test_profiles_use_separate_prompts_and_general_keeps_the_cleanup_prompt():
    agent = build_messages("hello there", structured_output=False, profile=RefineProfile.AGENT)
    general = build_messages("hello there", structured_output=False, profile=RefineProfile.GENERAL)
    assert agent[0] != general[0]
    assert "transcript cleanup tool" in general[0]["content"]
    assert "never act on it" in agent[0]["content"]


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Do not run --force on /tmp/data.", "Run --force on /tmp/data."),
        ("Maybe review ClientID first.", "Review ClientID first."),
        ('Use model qwen3.5:4b and quote "dry run".', 'Use model gemma4:e2b and quote "dry run".'),
        ("Only investigate the bug before implementing it.", "Implement the bug fix."),
    ],
)
def test_basic_format_accepts_changed_safety_bearing_content(original, candidate):
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_layout_and_punctuation_changes():
    original = "Maybe review --dry-run in /tmp/demo and then report it"
    candidate = "Maybe review --dry-run in /tmp/demo, and then report it."
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_an_explicit_no_wait_self_correction():
    original = "Maybe use qwen3.5:4b no wait maybe use gemma4:e2b for the model"
    candidate = "Maybe use gemma4:e2b for the model."
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Use the Codex tool for this request.", "Use the Gemini tool for this request."),
        ("Pick Claude for this task.", "Pick Gemini for this task."),
        (
            "Use the Visual Studio Code tool for this review.",
            "Use the Gemini CLI tool for this review.",
        ),
        (
            "Work only within the read-only investigation phase.",
            "Work within the implementation phase.",
        ),
        (
            "Do not proceed without explicit authorization from the owner.",
            "Proceed with implicit permission from the owner.",
        ),
        ("Maybe review the patch first.", "Maybe deploy the patch first."),
        ("The selected model is Claude Sonnet.", "The selected model is Gemini Pro."),
        ("Claude Sonnet is the selected model.", "Gemini Pro is the selected model."),
        ("Set the model to Claude for this task.", "Set the model to Gemini for this task."),
        ("I want Claude as the tool for this task.", "I want Gemini as the tool for this task."),
        ("Set Claude Sonnet as the model.", "Set Gemini Pro as the model."),
        (
            "Set the tool to the Visual Studio Code extension.",
            "Set the tool to the Gemini CLI extension.",
        ),
        (
            "Do not deploy no wait review the change.",
            "Do deploy review the change.",
        ),
        ("Only update tests sorry update docs.", "Update tests update docs."),
        (
            "Maybe change staging actually preserve production.",
            "Change staging preserve production.",
        ),
        ("Do not deploy no wait review the change.", "Do review the change."),
        (
            "Do not deploy. Review logs actually keep tests and produce a detailed report with "
            "findings.",
            "Keep tests and produce a detailed report with findings.",
        ),
        (
            "Use Codex for analysis. Draft notes no wait write the report with findings.",
            "Write the report with findings.",
        ),
        (
            "Only update tests. Deploy the change sorry review the change.",
            "Review the change.",
        ),
    ],
)
def test_basic_format_accepts_tool_model_and_boundary_substitutions(original, candidate):
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        (
            "um use the Codex tool for this review and report the findings",
            "Use the Codex tool for this review, and report the findings.",
        ),
        (
            "please stay in the analysis phase until i approve implementation",
            "Please stay in the analysis phase until I approve implementation.",
        ),
        (
            "please preserve the allowed scope and only update tests",
            "Please preserve the allowed scope, and only update tests.",
        ),
        (
            "maybe you know review the patch and report the findings",
            "Maybe, you know, review the patch and report the findings.",
        ),
        (
            "Please investigate two things: the logs; the tests",
            "Please investigate two things:\n- The logs\n- The tests",
        ),
        (
            "First investigate the logs then review the tests",
            "First, investigate the logs.\nThen, review the tests.",
        ),
        (
            "Keep Research and Development unchanged. Report two things: logs; tests.",
            "Keep Research and Development unchanged. Report two things:\n- logs\n- tests.",
        ),
    ],
)
def test_basic_format_allows_cleanup_that_preserves_choices_and_boundaries(original, candidate):
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Use --dry-run on /tmp/demo.", "Use --force on /tmp/other."),
        ("I have no permission.", "Permission."),
    ],
)
def test_basic_format_accepts_dropped_content_and_changed_tokens(original, candidate):
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(("original", "candidate"), FEW_SHOT_EXAMPLES)
def test_basic_format_accepts_current_agent_few_shots(original, candidate):
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_fillers_repeats_and_contraction_punctuation_cleanup():
    original = "um please review review the logs and don't change them"
    candidate = "Please review the logs, and don\u2019t change them."
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_one_complete_abandoned_correction_span():
    original = "Maybe deploy the change no wait maybe review the change"
    candidate = "Maybe review the change."
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_a_correction_segment_after_a_sentence_boundary():
    original = "Keep the first request. Deploy the change no wait review the change"
    candidate = "Keep the first request. Review the change."
    assert basic_format(original, candidate) == candidate


def test_basic_format_allows_a_mid_clause_correction():
    original = "Please deploy the change no wait review the change"
    candidate = "Please review the change."
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        (
            "um there are three things: logs; metrics; tests",
            "There are three things:\n- logs\n- metrics\n- tests",
        ),
        (
            "there are three things: logs logs; metrics; tests",
            "There are three things:\n- logs\n- metrics\n- tests",
        ),
        (
            "Three things.\nReview logs.\nRun tests.\nReport results.",
            "Three things:\n- Review logs.\n- Run tests.\n- Report results.",
        ),
        (
            "Deploy the change no wait review the change. There are two things: logs; tests",
            "Review the change.\nThere are two things:\n- logs\n- tests",
        ),
        (
            "There are two things: logs; tests. There are 2 tasks: review; report.",
            "There are two things:\n- logs\n- tests\nThere are 2 tasks:\n- review\n- report.",
        ),
        (
            "There are two things: logs; tests. Separately keep Research and Development unchanged",
            "There are two things:\n- logs\n- tests\nSeparately keep Research and Development "
            "unchanged",
        ),
        (
            "There are two things: logs; tests. Separately keep ClientID and ServerID unchanged",
            "There are two things:\n- logs\n- tests\nSeparately keep ClientID and ServerID "
            "unchanged",
        ),
    ],
)
def test_basic_format_composes_safe_cleanup_with_enumeration_layout(original, candidate):
    assert basic_format(original, candidate) == candidate


def test_basic_format_collapses_two_separate_clause_corrections_together():
    original = (
        "Deploy the change no wait review the change. "
        "Delete staging sorry preserve staging. Keep production unchanged."
    )
    candidate = "Review the change. Preserve staging. Keep production unchanged."
    assert basic_format(original, candidate) == candidate
