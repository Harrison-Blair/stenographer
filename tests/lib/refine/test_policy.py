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
    pull_url,
    tags_url,
)
from stenographer.lib.refine.policy import (
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
