# SPDX-License-Identifier: GPL-3.0-or-later
"""The refiner's fail-open contract, and what it records about each attempt.

``post_chat``, ``is_model_loaded`` and ``warm_model`` are the only seams
replaced here — the module boundary the package itself already draws around
``urllib`` — so the request builder, the parser, the guard, the classification,
and the measurement all run for real. Nothing starts a server and nothing
touches the network.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

from stenographer.lib.config.models import Config, RefineConfig
from stenographer.lib.refine import ollama_refiner
from stenographer.lib.refine.errors import RefineTimeoutError, RefineTransportError
from stenographer.lib.refine.factory import build_refiner
from stenographer.lib.refine.ollama_refiner import OllamaRefiner
from stenographer.lib.refine.results import (
    OUTCOME_APPLIED,
    OUTCOME_FAILED,
    OUTCOME_REJECTED,
    OUTCOME_SKIPPED,
    OUTCOME_TIMEOUT,
)
from tests.lib.refine.helpers import CLEANED, SPOKEN, _answer, _refiner
from tests.lib.refine.helpers import transport as transport


def test_a_clean_reply_is_delivered_and_measured(transport):
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == CLEANED

    result = refiner.last_result
    assert result.outcome == OUTCOME_APPLIED
    assert result.applied is True and result.failed is False and result.attempted is True
    assert result.chars_in == len(SPOKEN)
    assert result.chars_out == len(CLEANED)
    assert result.duration_ms is not None and result.duration_ms >= 0


def test_threshold_admits_exactly_min_words_and_refuses_one_short():
    refiner = _refiner(min_words=10)
    assert refiner.will_refine("one two three four five six seven eight nine ten")
    assert not refiner.will_refine("one two three four five six seven eight nine")


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_is_never_refined(text):
    assert not _refiner(min_words=1).will_refine(text)


def test_a_cold_model_is_loaded_on_its_own_budget_before_the_utterance_is_timed(transport):
    """The utterance budget assumes a warm model. A cold load must get the
    long budget first, and only then is the ordinary one started."""
    transport["loaded"] = False
    refiner = _refiner(keep_alive=-1)

    assert refiner.refine(SPOKEN) == CLEANED
    assert refiner.last_result.outcome == OUTCOME_APPLIED

    (warm,) = transport["warm_calls"]
    assert warm["model"] == "test-model"
    assert warm["keep_alive"] == -1
    assert warm["timeout"] == pytest.approx(120.0)
    (chat,) = transport["calls"]
    assert chat["timeout"] == pytest.approx(10.78)


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (RefineTimeoutError("ollama did not answer in time"), OUTCOME_TIMEOUT),
        (RefineTransportError("ollama could not be reached"), OUTCOME_FAILED),
    ],
)
def test_a_load_that_does_not_finish_delivers_the_raw_text_without_a_chat(
    transport, failure, outcome
):
    transport["loaded"] = False
    transport["warm_raise"] = failure
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == outcome
    assert refiner.last_result.failed is True
    assert transport["calls"] == []


def test_short_text_never_reaches_the_model(transport):
    refiner = _refiner()
    short = "just five words here now "

    assert refiner.will_refine(short) is False
    assert refiner.refine(short) == short
    assert transport["calls"] == []
    assert refiner.last_result.outcome == OUTCOME_SKIPPED
    assert refiner.last_result.attempted is False


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        (RefineTimeoutError("ollama did not answer in time"), OUTCOME_TIMEOUT),
        (RefineTransportError("ollama could not be reached"), OUTCOME_FAILED),
        (RuntimeError("something unexpected"), OUTCOME_FAILED),
    ],
)
def test_every_failure_delivers_the_raw_text_and_is_classified(transport, failure, outcome):
    transport["raise"] = failure
    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == outcome
    assert refiner.last_result.failed is True
    assert refiner.last_result.chars_out is None


def test_a_cold_load_reports_loading_only_around_the_warm_request(transport, monkeypatch):
    transport["loaded"] = False
    order: list[str] = []
    real_warm = ollama_refiner.warm_model

    def warm_model(*args, **kwargs):
        order.append("warm_start")
        real_warm(*args, **kwargs)
        order.append("warm_end")

    monkeypatch.setattr(ollama_refiner, "warm_model", warm_model)
    refiner = _refiner(
        on_model_loading=lambda: order.append("loading"),
        on_model_loading_finished=lambda: order.append("finished"),
    )

    assert refiner.refine(SPOKEN) == CLEANED

    assert order == ["loading", "warm_start", "warm_end", "finished"]


def test_a_resident_model_reports_no_loading(transport):
    events: list[str] = []
    refiner = _refiner(
        on_model_loading=lambda: events.append("loading"),
        on_model_loading_finished=lambda: events.append("finished"),
    )

    assert refiner.refine(SPOKEN) == CLEANED

    assert events == []


def test_a_failed_load_still_reports_finished(transport):
    transport["loaded"] = False
    transport["warm_raise"] = RefineTimeoutError("ollama did not answer in time")
    events: list[str] = []
    refiner = _refiner(
        on_model_loading=lambda: events.append("loading"),
        on_model_loading_finished=lambda: events.append("finished"),
    )

    assert refiner.refine(SPOKEN) == SPOKEN

    assert refiner.last_result.outcome == OUTCOME_TIMEOUT
    assert events == ["loading", "finished"]


@pytest.mark.parametrize("warm_raise", [None, RefineTransportError("ollama could not be reached")])
def test_the_startup_warm_reports_loading_and_finished(transport, warm_raise):
    transport["warm_raise"] = warm_raise
    events: list[str] = []
    refiner = _refiner(
        on_model_loading=lambda: events.append("loading"),
        on_model_loading_finished=lambda: events.append("finished"),
    )

    result = refiner.warm()

    assert events == ["loading", "finished"]
    assert result is (warm_raise is None)


def test_a_loading_observer_that_raises_never_changes_the_outcome(transport, caplog):
    transport["loaded"] = False

    def broken_loading():
        raise RuntimeError("observer exploded")

    refiner = _refiner(on_model_loading=broken_loading)

    with caplog.at_level(logging.WARNING, logger="stenographer.lib.refine"):
        assert refiner.refine(SPOKEN) == CLEANED

    assert refiner.last_result.outcome == OUTCOME_APPLIED
    observer_lines = [m for m in caplog.messages if "observer_failed" in m]
    assert len(observer_lines) == 1
    assert "refine: observer_failed" in observer_lines[0]
    text = "\n".join(caplog.messages)
    assert "thursday" not in text and "friday" not in text.casefold()


def test_a_reply_the_guard_refuses_delivers_the_raw_text(transport):
    transport["reply"] = _answer("Friday.")

    refiner = _refiner()

    assert refiner.refine(SPOKEN) == SPOKEN
    assert refiner.last_result.outcome == OUTCOME_REJECTED


def test_a_malformed_reply_delivers_the_raw_text(transport):
    transport["reply"] = b"<html>proxy error</html>"

    assert _refiner().refine(SPOKEN) == SPOKEN


def test_no_transcript_or_reply_text_ever_reaches_the_log(transport, caplog):
    transport["reply"] = _answer(f"{SPOKEN} {SPOKEN} {SPOKEN} {SPOKEN}")

    with caplog.at_level(logging.DEBUG, logger="stenographer.lib.refine"):
        assert _refiner().refine(SPOKEN) == SPOKEN

    text = "\n".join(caplog.messages)
    assert "refine: not_applied" in text
    assert "thursday" not in text and "friday" not in text.casefold()


def test_plain_text_replies_work_without_the_schema(transport):
    transport["reply"] = _answer(CLEANED, structured=False)

    assert _refiner(structured_output=False).refine(SPOKEN) == CLEANED


@pytest.mark.parametrize(
    "section",
    [
        RefineConfig(enabled=False),
        RefineConfig(enabled=True, model="   "),
        RefineConfig(enabled=True, host=""),
    ],
)
def test_the_factory_builds_nothing_that_can_reach_the_network(section):
    assert build_refiner(section, idle_unload_seconds=900) is None


def test_the_factory_carries_the_asr_idle_window_into_keep_alive():
    refiner = build_refiner(RefineConfig(enabled=True), idle_unload_seconds=0)

    assert isinstance(refiner, OllamaRefiner)
    assert refiner._keep_alive == -1
    assert build_refiner(RefineConfig(enabled=True), idle_unload_seconds=-1)._keep_alive == -1
    assert build_refiner(RefineConfig(enabled=True), idle_unload_seconds=60)._keep_alive == 60


@pytest.mark.parametrize(
    ("configured", "override", "expected"), [(False, True, True), (True, False, False)]
)
def test_explicit_override_controls_the_factory(configured, override, expected):
    section = dataclasses.replace(Config.defaults().refine, enabled=configured)
    refiner = build_refiner(section, idle_unload_seconds=900, enabled=override)
    assert isinstance(refiner, OllamaRefiner) is expected


def test_the_factory_passes_the_loading_observers_through(transport):
    transport["loaded"] = False
    transport["reply"] = _answer(CLEANED, structured=False)
    events = []
    refiner = build_refiner(
        RefineConfig(enabled=True),
        idle_unload_seconds=900,
        on_model_loading=lambda: events.append("loading"),
        on_model_loading_finished=lambda: events.append("finished"),
    )
    assert refiner.refine(SPOKEN) == CLEANED
    assert events == ["loading", "finished"]


def test_the_factory_hands_the_vocabulary_to_the_request(transport):
    section = RefineConfig(enabled=True, vocabulary=("Kubernetes", "PipeWire"))

    build_refiner(section, idle_unload_seconds=900).refine(SPOKEN)

    system_text = " ".join(
        message["content"]
        for message in transport["calls"][0]["body"]["messages"]
        if message["role"] == "system"
    )
    assert "Kubernetes" in system_text
    assert "PipeWire" in system_text


@pytest.mark.parametrize("failure", [None, RefineTransportError("connection refused")])
def test_vocabulary_terms_never_reach_the_log(transport, caplog, failure):
    transport["raise"] = failure
    transport["loaded"] = False
    refiner = _refiner(vocabulary=("Zebulonterm", "Quixarvel"))

    with caplog.at_level(logging.DEBUG, logger="stenographer"):
        refiner.refine(SPOKEN)
        refiner.warm()

    text = "\n".join(caplog.messages)
    assert "Zebulonterm" not in text
    assert "Quixarvel" not in text
