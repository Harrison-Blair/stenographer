# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent accepts substantial rewrites; General retains its cleanup contract."""

import pytest

from stenographer.lib.refine.errors import RefineRejectedError
from stenographer.lib.refine.response import basic_format, guard

REWRITES = (
    (
        "The request was rejected by the server because the credentials had expired.",
        "The server rejected the request because the credentials expired.",
    ),
    (
        "The cache expires after 30 seconds. The cache expires after 30 seconds.",
        "The cache expires after 30 seconds.",
    ),
    (
        "Please repair the defect and modify the timeout. Erase the unused entry.",
        "Fix the defect. Change the timeout. Remove the unused entry.",
    ),
    (
        "The report is needed on Friday. The deployment failed. We need the report on Friday.",
        "The deployment failed. We need the report on Friday.",
    ),
    (
        ("Um okay so I want to I want to ask you to please review the logs. " * 8),
        "Please review the logs.",
    ),
)


@pytest.mark.parametrize(("original", "candidate"), REWRITES)
def test_agent_accepts_substantial_rewrites(original, candidate):
    assert basic_format(original, candidate) == candidate


def test_general_still_rejects_duplicate_numeral_compression():
    original, candidate = REWRITES[1]
    with pytest.raises(RefineRejectedError):
        guard(original, candidate)


def test_general_still_rejects_deep_compression():
    original, candidate = REWRITES[-1]
    with pytest.raises(RefineRejectedError):
        guard(original, candidate)


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("If the check fails, only review it.", "Only review it."),
        ("Validate the proposal only.", "Check the proposal only."),
        ("Investigate the failure.", "Investigation of the failure."),
        ("Maybe the cache failed.", "The cache failed."),
        ("Don't change the timeout.", "Change the timeout."),
        ("Use --dry-run on /tmp/demo.", "Use --force on /tmp/demo."),
        ('Keep "dry run" in ClientID.', 'Keep "run" in ClientID.'),
        ("Use qwen3:8b for review.", "Use qwen3:4b for review."),
        ("The limit is 30. The timeout is 30.", "The limit and timeout are 40."),
        (
            "The limit is 30 for database requests. Separately the timeout is 30 no wait 40.",
            "The limit and timeout are 40.",
        ),
        ("Review the log.", "Repair the log."),
        ("I sent a repair for review.", "Fix the defect for review."),
    ],
)
def test_agent_accepts_changed_values_and_boundary_words(original, candidate):
    assert basic_format(original, candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Don't change it. Do not change it.", "Do not change it."),
        ("If it fails review it. If it fails review it.", "If it fails, review it."),
        ("Maybe review it. Maybe review it.", "Maybe review it."),
        (
            "Use ClientID with --dry-run. Use ClientID with --dry-run.",
            "Use ClientID with --dry-run.",
        ),
        ("Alter the timeout.", "Modify the timeout."),
        ("Fix the defect.", "Repair the defect."),
    ],
)
def test_agent_consolidates_repeated_boundaries_and_compares_aliases_symmetrically(
    original, candidate
):
    assert basic_format(original, candidate) == candidate


def test_agent_accepts_an_introduced_detected_name():
    candidate = "Contact Codex and Microsoft about the request."
    assert basic_format("Contact Codex about the request.", candidate) == candidate


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        ("Claude should review the parser.", "The parser is what Claude should review."),
        ("Today review the parser.", "Review the parser Today."),
    ],
)
def test_sentence_initial_source_words_can_move_without_becoming_new_names(original, candidate):
    assert basic_format(original, candidate) == candidate
