# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in end-to-end check against a real local Ollama.

Never collected without ``STENOGRAPHER_INTEGRATION=1``, and it still skips
unless an Ollama actually answers on the configured host with the configured
model already installed: this suite may not pull models. It is the only test in
the project that speaks to a model.

It warms the model first, exactly as the daemon does at start, so the cold load
is not charged against the per-utterance budget. A machine whose GPU is already
busy with something else can still miss that budget; a timeout here is the
fail-open path working, not the feature being broken.
"""

from __future__ import annotations

import pytest

from stenographer.lib.config.models import Config
from stenographer.lib.refine.client import installed_model_names
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.policy import keep_alive_for
from stenographer.lib.refine.results import OUTCOME_APPLIED

pytestmark = pytest.mark.integration

SPOKEN = (
    "um so i think we should ship it on thursday no wait friday because the "
    "uh the release notes aren't done yet "
)


@pytest.fixture
def refiner() -> OllamaRefiner:
    section = Config.defaults().refine
    installed = installed_model_names(section.host)
    if not installed:
        pytest.skip(f"no Ollama answered at {section.host}")
    if section.model not in installed:
        pytest.skip(f"{section.model} is not installed; this suite never pulls models")
    built = OllamaRefiner(
        host=section.host,
        model=section.model,
        min_words=section.min_words,
        structured_output=section.structured_output,
        keep_alive=keep_alive_for(Config.defaults().asr.idle_unload_seconds),
    )
    if not built.warm():
        pytest.skip(f"{section.model} could not be loaded on {section.host}")
    return built


def test_a_real_model_cleans_a_dictated_sentence_within_the_budget(refiner):
    refined = refiner.refine(SPOKEN)

    result = refiner.last_result
    assert result.outcome == OUTCOME_APPLIED, result
    assert refined != SPOKEN
    assert refined.endswith(" "), "the dictation trailing space must survive"
    # Meaning preservation, checked on the one correction the sample makes.
    assert "friday" in refined.casefold()
    assert "thursday" not in refined.casefold()
    assert "um" not in refined.casefold().split()
