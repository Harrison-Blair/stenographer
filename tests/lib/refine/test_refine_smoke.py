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

from stenographer.lib.refine.results import OUTCOME_APPLIED
from tests.lib.refine.helpers import installed_refiner as installed_refiner

pytestmark = pytest.mark.integration

SPOKEN = (
    "um so i think we should ship it on thursday no wait friday because the "
    "uh the release notes aren't done yet "
)


def test_a_real_model_cleans_a_dictated_sentence_within_the_budget(installed_refiner):
    refiner = installed_refiner
    refined = refiner.refine(SPOKEN)

    result = refiner.last_result
    assert result.outcome == OUTCOME_APPLIED, result
    assert refined != SPOKEN
    assert refined.endswith(" "), "the dictation trailing space must survive"
    # Meaning preservation, checked on the one correction the sample makes.
    assert "friday" in refined.casefold()
    assert "thursday" not in refined.casefold()
    assert "um" not in refined.casefold().split()
