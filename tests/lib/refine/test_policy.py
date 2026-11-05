# SPDX-License-Identifier: GPL-3.0-or-later
"""The refine endpoint vocabulary."""

from __future__ import annotations

import pytest

from stenographer.lib.refine.endpoints import (
    api_url,
    host_name,
    is_loopback,
    normalize_host,
    qualify_tag,
)


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

    assert api_url(host, "chat") == "http://127.0.0.1:11434/api/chat"
    assert api_url(host, "tags") == "http://127.0.0.1:11434/api/tags"
    assert api_url(host, "pull") == "http://127.0.0.1:11434/api/pull"
    assert api_url(host, "generate") == "http://127.0.0.1:11434/api/generate"
    assert api_url(host, "ps") == "http://127.0.0.1:11434/api/ps"


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
