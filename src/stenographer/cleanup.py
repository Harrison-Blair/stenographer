# SPDX-License-Identifier: GPL-3.0-or-later
"""Experimental cleanup contracts and pure validation; never called by the daemon.

Validation proves an edit is structurally applicable, not semantically faithful.
Model/output strategy selection requires blinded human review of the corpus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from stenographer.inference import Failure, Result


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_output(
    original: str,
    response: str,
    *,
    strategy: str,
    finish_reason: str,
    input_complete: bool,
) -> Result[str]:
    """Reject truncation/empty/malformed output; never flatten accepted layout.

    Edit offsets count Unicode code points in the ORIGINAL string, are sorted,
    non-overlapping, and anchored to both its digest and the exact replaced text.
    A runtime must establish input_complete from its context-budget check; it
    must never assume a server accepted the full input merely because it replied.
    """
    if not input_complete:
        return Result(failure=Failure.CONTEXT)
    if finish_reason != "stop":
        return Result(failure=Failure.INVALID)
    if strategy == "rewrite":
        output = response
    elif strategy == "edits":
        try:
            document = json.loads(response)
            if (
                not isinstance(document, dict)
                or set(document) != {"source_sha256", "edits"}
                or document["source_sha256"] != source_hash(original)
                or not isinstance(document["edits"], list)
            ):
                return Result(failure=Failure.INVALID)
            pieces, cursor, previous_start = [], 0, -1
            for edit in document["edits"]:
                if not isinstance(edit, dict) or set(edit) != {"start", "end", "before", "after"}:
                    return Result(failure=Failure.INVALID)
                start, end = edit["start"], edit["end"]
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not cursor <= start <= end <= len(original)
                    or start <= previous_start
                    or not isinstance(edit["after"], str)
                    or original[start:end] != edit["before"]
                ):
                    return Result(failure=Failure.INVALID)
                pieces.extend((original[cursor:start], edit["after"]))
                cursor, previous_start = end, start
            output = "".join((*pieces, original[cursor:]))
        except (ValueError, TypeError, RecursionError):
            return Result(failure=Failure.INVALID)
    else:
        return Result(failure=Failure.INVALID)
    if not output.strip() or any(ord(char) < 32 and char not in "\n\t\r" for char in output):
        return Result(failure=Failure.INVALID)
    if "<think>" in output or "</think>" in output:
        return Result(failure=Failure.INVALID)
    return Result(value=output)


@dataclass(frozen=True)
class Selection:
    text: str | None = field(repr=False)
    cleanup_skipped: bool


def select_text(original: str, result: Result[str]) -> Selection:
    """Choose once, before delivery. Cancellation means no delivery at all."""
    if result.failure is Failure.CANCELLED:
        return Selection(None, False)
    if result.failure is not None:
        return Selection(original, True)
    if not result.value or not result.value.strip():
        return Selection(original, True)
    return Selection(result.value, False)
