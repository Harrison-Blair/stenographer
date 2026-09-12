# SPDX-License-Identifier: GPL-3.0-or-later
"""The parts of the Ollama client that decide something without a socket."""

from __future__ import annotations

import http.client
import io
import json

import pytest

from stenographer.lib.refine.client import (
    installed_model_bytes,
    installed_model_names,
    is_model_loaded,
    pull_progress_line,
    running_model_names,
)
from stenographer.lib.refine.errors import RefineError


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"status": "pulling manifest"}, "pulling manifest"),
        ({"status": "downloading", "completed": 50, "total": 200}, "downloading 25%"),
        ({"status": "downloading", "completed": 200, "total": 200}, "downloading 100%"),
        # A zero or missing total must not divide by zero or report a fake 0%.
        ({"status": "downloading", "completed": 5, "total": 0}, "downloading"),
        ({"status": "downloading", "completed": 5}, "downloading"),
        ({"completed": 5, "total": 10}, "pulling 50%"),
        ({}, "pulling"),
        ({"status": 7}, "pulling"),
    ],
)
def test_a_streamed_pull_record_renders_as_one_short_status_line(record, expected):
    assert pull_progress_line(record) == expected


def test_progress_lines_never_echo_anything_but_status_and_counters():
    """A pull record carries digests and file names; the console line is a
    status word and a percentage, so nothing else can reach the terminal."""
    line = pull_progress_line(
        {"status": "downloading", "digest": "sha256:deadbeef", "completed": 1, "total": 4}
    )

    assert line == "downloading 25%"


class _ResetStream:
    """A response whose body dies mid-download, as a dropped socket does."""

    def __init__(self, failure: Exception) -> None:
        self._failure = failure
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.closed = True

    def __iter__(self):
        yield b'{"status": "pulling manifest"}\n'
        raise self._failure


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ConnectionResetError("peer went away"), "could not be reached"),
        (TimeoutError("read stalled"), "did not answer in time"),
        (http.client.IncompleteRead(b"half"), "could not be reached"),
    ],
)
def test_a_pull_whose_stream_dies_raises_a_refine_error_not_a_traceback(
    monkeypatch, failure, expected
):
    """A multi-gigabyte download is exactly where a socket drops. The CLI
    reports a ``RefineError``; anything else reaches the user as a traceback.
    Seen to FAIL against an unguarded ``for line in response``.

    ``match=`` pins this to the translated socket failure specifically: fix
    1 gave ``pull_model`` a second ``RefineError`` source (a stream that
    simply ends without a terminal ``success`` line), which is exactly what
    a swallowed stream-read failure would also produce, so a bare
    ``pytest.raises(RefineError)`` no longer proves the socket death itself
    was caught and translated."""
    from stenographer.lib.refine import client as module

    monkeypatch.setattr(module, "_post", lambda url, body, timeout: _ResetStream(failure))

    with pytest.raises(RefineError, match=expected):
        module.pull_model("http://127.0.0.1:11434", "some:tag", on_progress=lambda line: None)


def test_a_pull_stream_reports_progress_until_it_fails(monkeypatch):
    """As above: the message is asserted so this stays pinned to the
    stream-read failure rather than to fix 1's separate missing-success
    check, which would also raise a ``RefineError`` once the stream ends."""
    from stenographer.lib.refine import client as module

    seen: list[str] = []
    monkeypatch.setattr(
        module, "_post", lambda url, body, timeout: _ResetStream(ConnectionResetError())
    )

    with pytest.raises(RefineError, match="could not be reached"):
        module.pull_model("http://127.0.0.1:11434", "some:tag", on_progress=seen.append)

    assert seen == ["pulling manifest"]


class _Reply(io.BytesIO):
    """A ``urlopen`` result: readable bytes that also work as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _serve_ps(monkeypatch, payload):
    import urllib.request

    seen: list[str] = []

    def urlopen(request, timeout):
        seen.append(request.full_url)
        if isinstance(payload, Exception):
            raise payload
        return _Reply(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


def test_the_residency_probe_reads_api_ps_and_reports_running_tags(monkeypatch):
    seen = _serve_ps(
        monkeypatch,
        {"models": [{"name": "gemma4:e2b", "model": "gemma4:e2b"}, {"model": "qwen3.5:4b"}, 7]},
    )

    assert running_model_names("http://127.0.0.1:11434/") == ["gemma4:e2b", "qwen3.5:4b"]
    assert seen == ["http://127.0.0.1:11434/api/ps"]
    assert is_model_loaded("http://127.0.0.1:11434", "gemma4:e2b") is True
    assert is_model_loaded("http://127.0.0.1:11434", "qwen3.5:4b") is True
    assert is_model_loaded("http://127.0.0.1:11434", "gemma3:4b") is False


@pytest.mark.parametrize(
    "payload",
    [ConnectionRefusedError(), TimeoutError(), {"models": "nope"}, [], {}],
)
def test_a_probe_that_cannot_answer_counts_as_nothing_loaded(monkeypatch, payload):
    """An unreachable or confused server is treated as cold: the caller then
    warms, and the warm is what reports the real failure."""
    _serve_ps(monkeypatch, payload)

    assert running_model_names("http://127.0.0.1:11434") == []
    assert is_model_loaded("http://127.0.0.1:11434", "gemma4:e2b") is False


def test_pull_with_no_progress_callback_still_detects_an_ollama_error(monkeypatch):
    """The documented default is ``on_progress=None``; an ``{"error": ...}``
    line must be noticed whether or not a caller passed a progress callback.
    Seen to FAIL when the error check sits below an ``on_progress is None``
    guard, since the loop body then never even parses the line.

    The stream ends with a ``success`` line so that only the error check --
    not the separate "stream never confirmed success" check -- can be what
    raises; without it, moving the error check back below the guard would
    still pass here by way of the *other* invariant, masking the regression
    this test exists to catch."""
    from stenographer.lib.refine import client as module

    stream = _Reply(
        b'{"status": "pulling manifest"}\n'
        b'{"error": "no space left on device"}\n'
        b'{"status": "success"}\n'
    )
    monkeypatch.setattr(module, "_post", lambda url, body, timeout: stream)

    with pytest.raises(RefineError, match="refused the pull"):
        module.pull_model("http://127.0.0.1:11434", "some:tag")


def test_a_pull_stream_that_ends_without_a_success_status_is_a_failure(monkeypatch):
    """A stream can simply end early -- a half-closed socket, a restarted
    server -- without ever sending ``{"error": ...}``. Only a terminal
    ``status: success`` line proves the model actually landed on disk.
    Seen to FAIL when the loop returns normally once iteration ends, with no
    check for whether success was ever reported. No line here carries an
    ``error`` field, so ``match=`` pins this to the missing-success check
    specifically, not to the separate error-detection invariant."""
    from stenographer.lib.refine import client as module

    stream = _Reply(b'{"status": "pulling manifest"}\n{"status": "verifying sha256 digest"}\n')
    monkeypatch.setattr(module, "_post", lambda url, body, timeout: stream)

    with pytest.raises(RefineError, match="without confirming success"):
        module.pull_model("http://127.0.0.1:11434", "some:tag", on_progress=lambda line: None)


def test_a_pull_stream_that_ends_with_success_reports_no_error(monkeypatch):
    """The positive case: a terminal ``status: success`` line is enough,
    whether or not any progress lines preceded it."""
    from stenographer.lib.refine import client as module

    stream = _Reply(b'{"status": "pulling manifest"}\n{"status": "success"}\n')
    monkeypatch.setattr(module, "_post", lambda url, body, timeout: stream)

    module.pull_model("http://127.0.0.1:11434", "some:tag")


def test_is_model_loaded_matches_an_untagged_config_name_against_ollamas_qualified_tag(
    monkeypatch,
):
    """Ollama reports resident models fully qualified (``gemma4:latest``); a
    config value with no tag (``gemma4``) must match the same way
    ``ollama run gemma4`` would. Seen to FAIL before the untagged name is
    qualified prior to the membership test."""
    _serve_ps(monkeypatch, {"models": [{"model": "gemma4:latest"}]})

    assert is_model_loaded("http://127.0.0.1:11434", "gemma4") is True


def test_installed_model_names_reports_exactly_what_ollama_sent_no_more(monkeypatch):
    """installed_model_names(...) is rendered verbatim as a numbered picker in
    ``stenographer setup`` (cli/setup/workflow.py); synthesizing a bare alias
    here would show the same installed model twice under two different
    numbers. The list must be exactly what ``/api/tags`` reported, sorted,
    with no invented duplicates."""
    _serve_ps(monkeypatch, {"models": [{"name": "gemma4:latest"}, {"name": "qwen3.5:4b"}]})

    assert installed_model_names("http://127.0.0.1:11434") == ["gemma4:latest", "qwen3.5:4b"]


def test_installed_model_names_drops_a_non_string_name_instead_of_stringifying_it(monkeypatch):
    """A malformed listing from a broken or foreign server -- ``{"name": 7}``
    -- must not render as the picker row ``'7'``; it is dropped like any
    other entry this module cannot make sense of."""
    _serve_ps(monkeypatch, {"models": [{"name": "gemma4:latest"}, {"name": 7}]})

    assert installed_model_names("http://127.0.0.1:11434") == ["gemma4:latest"]


def test_installed_model_bytes_matches_a_bare_config_value_against_a_qualified_listing(
    monkeypatch,
):
    """installed_model_bytes qualifies both sides, rather than narrowing back
    to an exact string match: a bare config value must still find the size
    of a fully-tagged entry."""
    _serve_ps(monkeypatch, {"models": [{"name": "gemma4:latest", "size": 3_000_000_000}]})

    assert installed_model_bytes("http://127.0.0.1:11434", "gemma4") == 3_000_000_000


def test_installed_model_bytes_matches_a_qualified_config_value_against_a_bare_listing(
    monkeypatch,
):
    """The reverse direction, defensive the same way: should a listing ever
    report a bare name, a fully-tagged config value must still find it."""
    _serve_ps(monkeypatch, {"models": [{"name": "gemma4", "size": 3_000_000_000}]})

    assert installed_model_bytes("http://127.0.0.1:11434", "gemma4:latest") == 3_000_000_000
