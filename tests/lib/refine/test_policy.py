# SPDX-License-Identifier: GPL-3.0-or-later
"""The two arithmetic decisions of the refine stage, and the endpoint vocabulary."""

from __future__ import annotations

import pytest

from stenographer.lib.refine.endpoints import (
    chat_url,
    generate_url,
    host_name,
    is_loopback,
    normalize_host,
    ps_url,
    pull_url,
    qualify_tag,
    tags_url,
)
from stenographer.lib.refine.policy import (
    COLD_LOAD_TIMEOUT_SECONDS,
    INDEFINITE_KEEP_ALIVE,
    keep_alive_for,
    should_refine,
    timeout_seconds,
    word_count,
)


def test_threshold_admits_exactly_min_words_and_refuses_one_short():
    ten = "one two three four five six seven eight nine ten"

    assert word_count(ten) == 10
    assert should_refine(ten, 10) is True
    assert should_refine("one two three four five six seven eight nine", 10) is False


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_is_never_refined_whatever_the_threshold(text):
    assert should_refine(text, 1) is False


def test_threshold_counts_words_the_way_analytics_does():
    """A count that disagreed with ``recognized_words`` would make a summary
    line contradict itself: 12 words recorded, refine skipped at min_words=10."""
    from stenographer.lib.analytics.metrics import count_words

    spoken = "it's a well-known problem, isn't it? 42 times over"
    assert word_count(spoken) == count_words(spoken)


def test_timeout_is_ten_seconds_plus_sixty_milliseconds_per_word():
    assert timeout_seconds(0) == pytest.approx(10.0)
    assert timeout_seconds(10) == pytest.approx(10.6)
    assert timeout_seconds(200) == pytest.approx(22.0)
    # A negative count cannot shorten the budget below its fixed floor.
    assert timeout_seconds(-5) == pytest.approx(10.0)


def test_a_cold_load_gets_its_own_two_minute_budget_outside_the_utterance_one():
    """Loading a model into VRAM is not decoding; it must never be charged
    against the ten-second utterance budget and must still end eventually."""
    assert pytest.approx(120.0) == COLD_LOAD_TIMEOUT_SECONDS
    assert timeout_seconds(1000) < COLD_LOAD_TIMEOUT_SECONDS


def test_keep_alive_follows_the_asr_idle_window_and_never_expires_at_zero():
    assert keep_alive_for(900) == 900
    assert keep_alive_for(0) == INDEFINITE_KEEP_ALIVE
    assert keep_alive_for(-1) == INDEFINITE_KEEP_ALIVE


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
        ("127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("  localhost:11434  ", "http://localhost:11434"),
    ],
)
def test_host_is_normalized_rather_than_rejected(host, expected):
    assert normalize_host(host) == expected


@pytest.mark.parametrize(
    ("host", "name"),
    [
        ("http://127.0.0.1:11434", "127.0.0.1"),
        ("http://localhost", "localhost"),
        ("http://[::1]:11434", "[::1]"),
        ("https://user:pw@ollama.example.com:443/x", "ollama.example.com"),
    ],
)
def test_host_name_drops_the_port_credentials_and_path(host, name):
    assert host_name(host) == name


@pytest.mark.parametrize(
    "host",
    ["http://127.0.0.1:11434", "localhost:11434", "http://[::1]:11434", "http://127.9.9.9"],
)
def test_loopback_hosts_keep_the_transcript_on_this_machine(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "http://192.168.1.5:11434",
        "https://ollama.example.com",
        "http://10.0.0.2:11434",
        # Reported as remote on purpose: the banner must not need a resolver
        # to decide whether it has to warn.
        "http://my-loopback.example",
    ],
)
def test_anything_not_provably_local_is_reported_as_remote(host):
    assert is_loopback(host) is False


def test_endpoints_are_built_from_one_normalized_host():
    host = "127.0.0.1:11434/"

    assert chat_url(host) == "http://127.0.0.1:11434/api/chat"
    assert tags_url(host) == "http://127.0.0.1:11434/api/tags"
    assert pull_url(host) == "http://127.0.0.1:11434/api/pull"
    assert generate_url(host) == "http://127.0.0.1:11434/api/generate"
    assert ps_url(host) == "http://127.0.0.1:11434/api/ps"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("HTTP://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("Http://LocalHost:11434", "http://LocalHost:11434"),
        ("HTTPS://ollama.example.com", "https://ollama.example.com"),
    ],
)
def test_an_upper_case_scheme_is_normalized_rather_than_rejected(host, expected):
    """Schemes are case-insensitive in every URL parser; a config that spells
    one in capitals must not be refused. Seen to FAIL against a normalizer that
    left the scheme alone, which then missed the allowed-scheme membership."""
    assert normalize_host(host) == expected


@pytest.mark.parametrize("host", ["http://", "https://", "   ", "http:///path"])
def test_a_host_with_no_authority_normalizes_to_something_with_no_name(host):
    """``http://`` names no server. Seen to FAIL against a normalizer that
    turned it into ``http://http:`` by re-prefixing its own scheme."""
    assert host_name(normalize_host(host)) == ""


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:11434",  # scheme-less, from test_host_is_normalized_rather_than_rejected
        "http://127.0.0.1:11434/",  # trailing slash, same test
        "http://127.0.0.1:11434//",  # more than one trailing slash
        "HTTP://127.0.0.1:11434",  # upper-case scheme, from test_an_upper_case_scheme_...
        "HTTP://127.0.0.1:11434/",  # upper-case scheme plus a trailing slash together
        "http://[::1]:11434",  # IPv6 literal, from test_host_name_drops_the_port_...
        "https://user:pw@ollama.example.com:443/x",  # host with a path, same test
        "  http://127.0.0.1:11434  ",  # surrounding whitespace, from test_host_is_normalized_...
    ],
)
def test_normalize_host_is_idempotent(host):
    """The setup wizard now normalizes the host it prompts for so its saved
    value round-trips against what the config layer normalizes again on
    load (see cli/setup); that equality holds only if normalizing an
    already-normalized host is a no-op. Every shape this module treats
    specially -- a bare host, a trailing slash, an upper-case scheme, an
    IPv6 literal, a host with a path -- must settle to a fixed point on the
    first pass, not keep changing on a second."""
    once = normalize_host(host)
    assert normalize_host(once) == once


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemma4", "gemma4:latest"),
        ("gemma4:e2b", "gemma4:e2b"),
        ("gemma4:latest", "gemma4:latest"),
        # A colon before the model's registry path is a port, not a tag: it
        # must not be mistaken for one and left unqualified.
        ("localhost:5000/gemma4", "localhost:5000/gemma4:latest"),
        ("localhost:5000/gemma4:e2b", "localhost:5000/gemma4:e2b"),
    ],
)
def test_qualify_tag_only_treats_a_colon_after_the_last_slash_as_a_tag(model, expected):
    """Seen to FAIL for the registry-port cases against a qualifier that
    checks ``":" in model`` over the whole string: a custom registry name
    such as ``localhost:5000/gemma4`` would then be left bare forever,
    reproducing the exact never-matches bug fix 2 set out to remove."""
    assert qualify_tag(model) == expected
