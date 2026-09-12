# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure checks for public-corpus refinement diagnostics; no server calls."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from stenographer.lib.config.models import RefineConfig

_PATH = Path(__file__).resolve().parents[2] / "scripts/transcription_study/refinement.py"
_SPEC = importlib.util.spec_from_file_location("study_refinement", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize(
    "host",
    ["http://127.0.0.1:11434", "127.2.3.4:11434", "https://[::1]:11434/", "http://localhost"],
)
def test_loopback_endpoints(host: str) -> None:
    assert _MODULE.loopback_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "http://example.com",
        "http://192.168.1.1",
        "http://0.0.0.0",
        "http://127.999.0.1",
        "ftp://127.0.0.1",
        "http://user:password@127.0.0.1",
        "http://127.0.0.1/path",
        "http://127.0.0.1?next=example.com",
        "http://127.0.0.1#extra",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
        "http://[broken",
        "",
    ],
)
def test_remote_and_ambiguous_endpoints_rejected(host: str) -> None:
    assert not _MODULE.loopback_host(host)


def test_protected_lexical_changes_separate_correction_from_loss() -> None:
    result = _MODULE.protected_metrics(
        "Alice will not order two boxes and three books",
        "Alice will not order two boxes and four books",
        "Alice will order two boxes and three books",
        protected_names=("Alice",),
    )
    assert result["negations"]["lost_correct"] == 1
    assert result["numbers"]["gained_correct"] == 1
    assert result["numbers"]["lost_correct"] == 0
    assert result["names"]["output_matching"] == 1
    assert result["names_evaluated"]
    assert not result["cleanup_reference_available"]
    assert "Alice" not in str(result)


def test_repeated_negation_counts_and_new_negation() -> None:
    result = _MODULE.protected_metrics("no no no", "no no no", "no never")
    assert result["negations"]["reference"] == 3
    assert result["negations"]["lost_correct"] == 2
    assert result["negations"]["added_nonreference"] == 1


def test_contractions_unicode_quotes_and_case_are_equivalent() -> None:
    result = _MODULE.protected_metrics(
        "DON'T change 17", "Don\u2019t change 17.", "don't change 17"
    )
    assert result["negations"]["output_matching"] == 1
    assert result["numbers"]["output_matching"] == 1
    assert not result["names_evaluated"]


def test_cleanup_or_digit_formatting_is_not_a_semantic_judgment() -> None:
    result = _MODULE.protected_metrics("um two boxes", "um two boxes", "2 boxes")
    assert result["numbers"]["lost_correct"] == 1
    assert result["numbers"]["added_nonreference"] == 1
    assert not result["cleanup_reference_available"]


def test_changed_decimal_is_not_hidden_by_bag_of_digit_fragments() -> None:
    result = _MODULE.protected_metrics("use 1.7 liters", "use 1.7 liters", "use 7.1 liters")
    assert result["numbers"]["reference"] == 1
    assert result["numbers"]["lost_correct"] == 1
    assert result["numbers"]["added_nonreference"] == 1


def test_disabled_refinement_scores_without_contacting_configured_host(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(_PATH.parent.parent))
    result = _MODULE.evaluate_refinement(
        "one red box", "one blue box", RefineConfig(enabled=False, host="https://example.com")
    )
    assert result["outcome"] == "disabled"
    assert result["S"] == 1
    assert result["duration_ms"] == 0


def test_below_threshold_uses_production_skip_without_server(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(_PATH.parent.parent))
    result = _MODULE.evaluate_refinement(
        "one red box",
        "one red box",
        RefineConfig(enabled=True, host="http://127.0.0.1:1", min_words=10),
    )
    assert result["outcome"] == "skipped"
    assert result["exact"]
    assert result["duration_ms"] == 0


def test_enabled_remote_refinement_rejected_before_construction(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(_PATH.parent.parent))
    with pytest.raises(ValueError, match="loopback"):
        _MODULE.evaluate_refinement("", "", RefineConfig(enabled=True, host="https://example.com"))


def test_disabled_metadata_does_not_probe_remote_server() -> None:
    result = _MODULE.refinement_metadata(RefineConfig(enabled=False, host="https://example.com"))
    assert result["metadata_status"] == "disabled"
    assert result["model_digest"] is None
    assert "host" not in result["config"]


def test_enabled_metadata_rejects_remote_server() -> None:
    with pytest.raises(ValueError, match="loopback"):
        _MODULE.refinement_metadata(RefineConfig(enabled=True, host="https://example.com"))
