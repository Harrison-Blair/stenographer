# SPDX-License-Identifier: GPL-3.0-or-later
"""The parts of the Ollama client that decide something without a socket."""

from __future__ import annotations

import http.client
import io
import json

import pytest

from stenographer.lib.refine.client import is_model_loaded, pull_progress_line, running_model_names
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
    "failure",
    [
        ConnectionResetError("peer went away"),
        TimeoutError("read stalled"),
        http.client.IncompleteRead(b"half"),
    ],
)
def test_a_pull_whose_stream_dies_raises_a_refine_error_not_a_traceback(monkeypatch, failure):
    """A multi-gigabyte download is exactly where a socket drops. The CLI
    reports a ``RefineError``; anything else reaches the user as a traceback.
    Seen to FAIL against an unguarded ``for line in response``."""
    from stenographer.lib.refine import client as module

    monkeypatch.setattr(module, "_post", lambda url, body, timeout: _ResetStream(failure))

    with pytest.raises(RefineError):
        module.pull_model("http://127.0.0.1:11434", "some:tag", on_progress=lambda line: None)


def test_a_pull_stream_reports_progress_until_it_fails(monkeypatch):
    from stenographer.lib.refine import client as module

    seen: list[str] = []
    monkeypatch.setattr(
        module, "_post", lambda url, body, timeout: _ResetStream(ConnectionResetError())
    )

    with pytest.raises(RefineError):
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
