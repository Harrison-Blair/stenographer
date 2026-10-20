# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in synthetic Agent acceptance through the production Ollama refiner.

Run with STENOGRAPHER_INTEGRATION=1, -s, and -m integration. Never pulls models.
The synthetic harness uses min_words=1 without changing application policy.
Mechanical assertions are necessary evidence, not proof of semantic fidelity;
inspect the output for all associations and details during machine acceptance.
"""

from __future__ import annotations

import re

import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.profiles import RefineProfile
from stenographer.lib.refine.results import OUTCOME_APPLIED
from tests.lib.refine.agent_acceptance_corpus import SEMANTIC_REGRESSIONS
from tests.lib.refine.test_refine_smoke import refiner as production_refiner

installed_refiner = production_refiner


@pytest.fixture
def refiner(installed_refiner):
    """Reuse the installed-model warm check; admit short synthetic inputs."""

    return OllamaRefiner(
        host=installed_refiner.host,
        model=installed_refiner.model,
        keep_alive=installed_refiner.keep_alive,
        structured_output=Config.defaults().refine.structured_output,
        min_words=1,
    )


pytestmark = pytest.mark.integration

# Each expected expression represents a distinct fact, reason, request, or limit.
CLARITY_CASES = (
    (
        "The report, um, is needed Friday because the audit is Monday. We need the report "
        "Friday. The outage was caused by the expired certificate. Just review the logs. "
        "Don't fix anything yet. Maybe the renewal job failed but I'm not sure. ",
        (
            r"\breport\b",
            r"\bFriday\b",
            r"\baudit\b",
            r"\bMonday\b",
            r"\boutage\b",
            r"\bexpired certificate\b",
            r"\bjust review\b",
            r"\blogs\b",
            r"\b(?:don't|do not) fix\b",
            r"\byet\b",
            r"\bmaybe\b",
            r"\brenewal job\b",
            r"\bfailed\b",
            r"\bnot sure\b",
        ),
    ),
    (
        "Please repair the defect in retry_handler.py and modify the timeout to 50 seconds. "
        "Erase the unused entry. The client identifier is ClientID. Validate the proposal only. ",
        (
            r"\bfix\b",
            r"\bdefect\b",
            r"retry_handler\.py",
            r"\bchange\b",
            r"\btimeout\b",
            r"\b50 seconds\b",
            r"\bremove\b",
            r"\bunused entry\b",
            r"\bclient\b",
            r"\bClientID\b",
            r"\bvalidate\b",
            r"\bproposal\b",
            r"\bonly\b",
        ),
    ),
    (
        "There are three requests, um open the config and then read the timeout and then "
        "report the timeout. Open the config, read the timeout, report the timeout. ",
        (r"\bopen\b.*\bconfig\b", r"\bread\b.*\btimeout\b", r"\breport\b.*\btimeout\b"),
    ),
    (
        "Parser requests time out after 30 seconds. Lexer requests time out after 30 seconds. "
        "I want the parser timeout reviewed only. Maybe fix the lexer timeout after I approve. ",
        (
            r"parser.*30 seconds",
            r"lexer.*30 seconds",
            r"\breview\w*\b",
            r"\bonly\b",
            r"\bmaybe\b",
            r"\bfix\b.*\blexer\b",
            r"\bafter I approve\b",
        ),
    ),
)


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


@pytest.mark.parametrize(("spoken", "expectations"), CLARITY_CASES)
def test_real_agent_rewrites_preserve_details_and_structure(refiner, spoken, expectations):
    output = refiner.refine(spoken, profile=RefineProfile.AGENT)
    assert refiner.last_result.outcome == OUTCOME_APPLIED, refiner.last_result
    print(f"\nSpoken input: {spoken}\nRequired details: {expectations}\nEdited dictation: {output}")
    assert output.endswith(" ")
    assert len(output) < len(spoken)
    for expectation in expectations:
        assert re.search(expectation, output, re.IGNORECASE), (expectation, output)
    assert ";" not in output
    sentences = re.split(r"[.!?](?:\s|$)|\n", output)
    assert all(len(sentence.split()) <= 25 for sentence in sentences)
    if spoken.startswith("There are three"):
        assert len(re.findall(r"(?m)^- ", output)) == 3


@pytest.mark.parametrize(
    ("case_id", "spoken", "wrong_output", "meaning_checklist"),
    SEMANTIC_REGRESSIONS,
    ids=[case[0] for case in SEMANTIC_REGRESSIONS],
)
def test_real_agent_avoids_known_semantic_regressions(
    refiner, case_id, spoken, wrong_output, meaning_checklist
):
    output = refiner.refine(spoken, profile=RefineProfile.AGENT)
    assert refiner.last_result.outcome == OUTCOME_APPLIED, (case_id, refiner.last_result)
    assert _normalized(output) != _normalized(wrong_output), (case_id, meaning_checklist, output)
    print(
        f"\n{case_id}\nSpoken input: {spoken}\n"
        f"Required meaning: {meaning_checklist}\nEdited dictation: {output}"
    )
    # Excluding one known wrong string cannot establish semantic fidelity.
    # Review every printed result against its human meaning checklist; Agent
    # has no semantic guard. Demand a model result rather than fallback.
    assert output.strip(), (case_id, output)
