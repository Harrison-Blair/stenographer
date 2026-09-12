# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic, lexical word-error scoring without storing transcript text."""

from __future__ import annotations

import re
import unicodedata

_WORDS = re.compile(r"\d+(?:[.,:]\d+)*|[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
_NEGATIONS = {"no", "not", "never", "neither", "nor", "nothing", "nobody", "without"}


def normalize(text: str) -> list[str]:
    """Ignore case and punctuation, preserving contractions and numeric values."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return _WORDS.findall(text)


def score(reference: str, hypothesis: str) -> dict:
    """Return minimum-edit counts and aligned boundary/protected-token metrics.

    Ties prefer substitution, then deletion, then insertion. No text is returned.
    WER is undefined (None) for an empty reference; false speech is explicit.
    """
    ref, hyp = normalize(reference), normalize(hypothesis)
    costs = [list(range(len(hyp) + 1))]
    for i, word in enumerate(ref, 1):
        row = [i]
        for j, other in enumerate(hyp, 1):
            row.append(
                min(costs[i - 1][j - 1] + (word != other), costs[i - 1][j] + 1, row[j - 1] + 1)
            )
        costs.append(row)
    i, j = len(ref), len(hyp)
    substitutions = deletions = insertions = 0
    matched = set()
    while i or j:
        if i and j and costs[i][j] == costs[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] == hyp[j - 1]:
                matched.add(i - 1)
            else:
                substitutions += 1
            i, j = i - 1, j - 1
        elif i and costs[i][j] == costs[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    numbers = {i for i, word in enumerate(ref) if any(char.isdigit() for char in word)}
    negations = {i for i, word in enumerate(ref) if word in _NEGATIONS or word.endswith("n't")}
    return {
        "S": substitutions,
        "D": deletions,
        "I": insertions,
        "N": len(ref),
        "wer": (substitutions + deletions + insertions) / len(ref) if ref else None,
        "exact": ref == hyp,
        "hypothesis_words": len(hyp),
        "opening_correct": 0 in matched if ref else None,
        "closing_correct": len(ref) - 1 in matched if ref else None,
        "number_count": len(numbers),
        "numbers_correct": len(numbers & matched),
        "negation_count": len(negations),
        "negations_correct": len(negations & matched),
        "false_speech": not ref and bool(hyp),
    }
