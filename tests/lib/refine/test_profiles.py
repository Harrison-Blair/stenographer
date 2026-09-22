# SPDX-License-Identifier: GPL-3.0-or-later
"""The two built-in refinement profiles and Agent's safety boundary."""

from __future__ import annotations

import pytest

from stenographer.lib.refine.agent_prompt import FEW_SHOT_EXAMPLES
from stenographer.lib.refine.errors import RefineRejectedError
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.request import build_messages
from stenographer.lib.refine.response import agent_guard


def test_exactly_two_builtin_profiles_with_agent_as_default():
    assert tuple(RefineProfile) == (RefineProfile.AGENT, RefineProfile.GENERAL)
    assert RefineProfile.default() is RefineProfile.AGENT


def test_profiles_use_separate_prompts_and_general_keeps_the_cleanup_prompt():
    agent = build_messages("hello there", structured_output=False, profile=RefineProfile.AGENT)
    general = build_messages("hello there", structured_output=False, profile=RefineProfile.GENERAL)
    assert agent[0] != general[0]
    assert "transcript cleanup tool" in general[0]["content"]
    assert "Do not perform" in agent[0]["content"]


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Do not run --force on /tmp/data.", "Run --force on /tmp/data."),
        ("Maybe review ClientID first.", "Review ClientID first."),
        ('Use model qwen3.5:4b and quote "dry run".', 'Use model gemma4:e2b and quote "dry run".'),
        ("Only investigate the bug before implementing it.", "Implement the bug fix."),
    ],
)
def test_agent_guard_rejects_changed_safety_bearing_content(original, candidate):
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


def test_agent_guard_allows_layout_and_punctuation_changes():
    original = "Maybe review --dry-run in /tmp/demo and then report it"
    candidate = "Maybe review --dry-run in /tmp/demo, and then report it."
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_allows_an_explicit_no_wait_self_correction():
    original = "Maybe use qwen3.5:4b no wait maybe use gemma4:e2b for the model"
    candidate = "Maybe use gemma4:e2b for the model."
    assert agent_guard(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Use the Codex tool for this request.", "Use the Gemini tool for this request."),
        ("Pick Claude for this task.", "Pick Gemini for this task."),
        (
            "Stay in the analysis phase until I approve implementation.",
            "Proceed in the deployment phase until I approve implementation.",
        ),
        ("Please preserve the allowed scope.", "Please expand the allowed scope."),
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
        ("Do not answer the request.", "Do not execute the request."),
        ("Maybe review the patch first.", "Maybe deploy the patch first."),
        ("Use the Codex tool for this.", "Use the tool Codex for this."),
        ("The selected model is Claude Sonnet.", "The selected model is Gemini Pro."),
        ("Claude Sonnet is the selected model.", "Gemini Pro is the selected model."),
        ("Set the model to Claude for this task.", "Set the model to Gemini for this task."),
        ("I want Claude as the tool for this task.", "I want Gemini as the tool for this task."),
        ("Treat foo as the identifier.", "Treat bar as the identifier."),
        ("Set Claude Sonnet as the model.", "Set Gemini Pro as the model."),
        ("The identifier is foo.", "The identifier is bar."),
        (
            "Set the tool to the Visual Studio Code extension.",
            "Set the tool to the Gemini CLI extension.",
        ),
        ("Only update tests, not source files.", "Only update source files, not tests."),
        (
            "Do not delete production; you may delete staging.",
            "Do not delete staging; you may delete production.",
        ),
        (
            "Maybe change staging, but preserve production.",
            "Maybe change production, but preserve staging.",
        ),
        ("Keep variable foo unchanged.", "Keep variable bar unchanged."),
        (
            "Do not deploy no wait review the change.",
            "Do deploy review the change.",
        ),
        ("Only update tests sorry update docs.", "Update tests update docs."),
        (
            "Maybe change staging actually preserve production.",
            "Change staging preserve production.",
        ),
        (
            "Research and Development covers two things logs and tests.",
            "Research Development covers two things:\n- logs\n- tests",
        ),
        ("values like null and false", "Values:\n- null\n- false"),
        ("Do not deploy no wait review the change.", "Do review the change."),
        ("Only update tests sorry update docs.", "Only update docs."),
        (
            "Maybe change staging actually preserve production.",
            "Maybe preserve production.",
        ),
        (
            "You may delete staging sorry preserve production.",
            "You preserve production.",
        ),
        ("Research and Development", "Research:\n- Development"),
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
        (
            "Keep Research and Development unchanged. Report two things logs and tests.",
            "Keep Research Development unchanged. Report two things:\n- logs\n- tests",
        ),
        (
            "There are two things logs and tests and separately keep Research and Development "
            "unchanged",
            "There are two things:\n- logs\n- tests\nand separately keep Research\n"
            "- Development unchanged",
        ),
        (
            "There are two things logs and tests and separately keep Research and Development "
            "unchanged",
            "There are two things:\n- logs and tests and separately keep Research\n"
            "- Development unchanged",
        ),
        (
            "There are two things logs and tests and separately keep ClientID and ServerID "
            "unchanged",
            "There are two things:\n- logs and tests and separately keep ClientID\n"
            "- ServerID unchanged",
        ),
        (
            "There are two things logs and tests and then keep Research and Development unchanged",
            "There are two things:\n- logs and tests and then keep Research\n"
            "- Development unchanged",
        ),
        (
            "There are two things logs and tests afterward keep ClientID and ServerID unchanged",
            "There are two things:\n- logs and tests afterward keep ClientID\n- ServerID unchanged",
        ),
        (
            "there are three things logs metrics and tests",
            "There are three things:\n- logs\n- metrics\n- tests",
        ),
        (
            "There are two things Research and Development and tests",
            "There are two things:\n- Research\n- Development and tests",
        ),
        (
            "There are two things ClientID and ServerID and logs",
            "There are two things:\n- ClientID\n- ServerID and logs",
        ),
        (
            "There are two things Washington, D.C., and tests",
            "There are two things:\n- Washington\n- D.C. and tests",
        ),
        (
            "There are three things Research and Development and tests",
            "There are three things:\n- Research\n- Development\n- tests",
        ),
        (
            "There are three things keep ClientID and ServerID unchanged and review logs",
            "There are three things:\n- keep ClientID\n- ServerID unchanged\n- review logs",
        ),
        (
            "There are three things do not change staging and production and review logs",
            "There are three things:\n- do not change staging\n- production\n- review logs",
        ),
        (
            "There are two things Washington, D.C.",
            "There are two things:\n- Washington\n- D.C.",
        ),
        (
            "there are three things logs, metrics, and tests",
            "There are three things:\n- logs\n- metrics\n- tests",
        ),
        (
            "There are two things Washington, D.C. officials",
            "There are two things:\n- Washington, D.C.\n- officials",
        ),
        (
            "There are two things Dr. Smith and review logs",
            "There are two things:\n- Dr.\n- Smith and review logs",
        ),
        (
            "There are two things e.g. staging and review production",
            "There are two things:\n- e.g.\n- staging and review production",
        ),
        (
            "Three things. Review logs. Run tests. Report results.",
            "Three things:\n- Review logs.\n- Run tests.\n- Report results.",
        ),
    ],
)
def test_agent_guard_rejects_tool_model_and_boundary_substitutions(original, candidate):
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


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
def test_agent_guard_allows_cleanup_that_preserves_choices_and_boundaries(original, candidate):
    assert agent_guard(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Review the logs.", "Please review the logs."),
        ("Review the logs and the tests.", "Review the tests."),
        ("Review the logs then the tests.", "Review the tests then the logs."),
        ("Don't change the files.", "Do not change the files."),
        ("Use --dry-run on /tmp/demo.", "Use --force on /tmp/other."),
        ("I have no permission.", "Permission."),
        ("I would rather review the tests.", "Review the tests."),
    ],
)
def test_agent_guard_rejects_lexical_additions_drops_and_reordering(original, candidate):
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


@pytest.mark.parametrize(("original", "candidate"), FEW_SHOT_EXAMPLES)
def test_agent_guard_accepts_current_agent_few_shots(original, candidate):
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_allows_fillers_repeats_and_contraction_punctuation_cleanup():
    original = "um please review review the logs and don't change them"
    candidate = "Please review the logs, and don\u2019t change them."
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_allows_one_complete_abandoned_correction_span():
    original = "Maybe deploy the change no wait maybe review the change"
    candidate = "Maybe review the change."
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_rejects_partial_deletion_from_an_abandoned_correction_span():
    original = "Maybe deploy the change no wait review the change"
    candidate = "Maybe the change review the change."
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


def test_agent_guard_allows_a_correction_segment_after_a_sentence_boundary():
    original = "Keep the first request. Deploy the change no wait review the change"
    candidate = "Keep the first request. Review the change."
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_rejects_ambiguous_mid_clause_correction_cleanup():
    original = "Please deploy the change no wait review the change"
    candidate = "Please review the change."
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


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
def test_agent_guard_composes_safe_cleanup_with_enumeration_layout(original, candidate):
    assert agent_guard(original, candidate) == candidate


def test_agent_guard_collapses_two_separate_clause_corrections_together():
    original = (
        "Deploy the change no wait review the change. "
        "Delete staging sorry preserve staging. Keep production unchanged."
    )
    candidate = "Review the change. Preserve staging. Keep production unchanged."
    assert agent_guard(original, candidate) == candidate
