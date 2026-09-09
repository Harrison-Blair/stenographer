# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure aggregation of private study evidence; no model, microphone, or downloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dictation_study import summarize_trials


def test_study_summary_order_failures_and_missing_measurements():
    counts = dict(errors=2, reference_words=10, empty=0, tail_insertions=1, opening_exact=1)
    records = [
        dict(variant="baseline", failure=None, decode_ms=10, **counts),
        dict(variant="replay", failure=None, stop_to_ready_ms=20, fallback=1, **counts),
        dict(variant="baseline", failure="RuntimeError", decode_ms=999),
        dict(variant="baseline", failure=None, decode_ms=30, **counts),
    ]
    summaries = summarize_trials(records, ["replay", "baseline", "absent"])
    assert [row["variant"] for row in summaries] == ["replay", "baseline", "absent"]
    replay, baseline, absent = summaries
    assert replay["decode_ms"] == dict(n=0, median=None, p95=None)
    assert replay["stop_to_ready_ms"] == dict(n=1, median=20, p95=20)
    assert replay["fallbacks"] == 1
    assert baseline["trials"] == 3 and baseline["failures"] == 1
    assert baseline["decode_ms"] == dict(n=2, median=20, p95=30)
    assert baseline["errors"] == 4 and baseline["reference_words"] == 20
    assert absent["trials"] == 0 and absent["decode_ms"]["median"] is None
    assert records[2]["decode_ms"] == 999
