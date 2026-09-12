# SPDX-License-Identifier: GPL-3.0-or-later
"""What the few-shot examples teach must be what the output guard accepts.

The benchmark found that the examples, not the rules, are what move the model,
so an example that demonstrates something the guard refuses would teach the
model to produce replies the stage then throws away.
"""

from __future__ import annotations

import re

import pytest

from stenographer.lib.refine.prompt import FEW_SHOT_EXAMPLES
from stenographer.lib.refine.response import guard

_ORDINAL_LINE = re.compile(r"^(?:And )?(First|Second|Third|Then|Next|Finally)\b", re.IGNORECASE)


@pytest.mark.parametrize(("spoken", "cleaned"), FEW_SHOT_EXAMPLES)
def test_every_example_answer_passes_the_guard_against_its_own_input(spoken, cleaned):
    assert guard(spoken, cleaned) == cleaned


def test_an_example_shows_ordinal_steps_as_lines_that_keep_their_own_words():
    """Ordinal words are the numbering. Seen to FAIL before the example existed:
    the model then either kept the steps in one paragraph or produced
    ``- first ...`` bullets, and a ``1.`` marker would be refused as an added
    numeral anyway."""
    answers = [cleaned for _, cleaned in FEW_SHOT_EXAMPLES]
    ordinal_answers = [
        cleaned
        for cleaned in answers
        if sum(bool(_ORDINAL_LINE.match(line)) for line in cleaned.splitlines()) >= 3
    ]

    assert ordinal_answers, "no example demonstrates an ordinal sequence"
    for cleaned in ordinal_answers:
        lines = cleaned.splitlines()
        assert not any(line.startswith("- ") for line in lines)
        assert not any(re.match(r"^\s*\d+[.)]", line) for line in lines)
