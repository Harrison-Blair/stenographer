# SPDX-License-Identifier: GPL-3.0-or-later
"""The title worker: when it asks the model, what it stores, and what it logs."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from stenographer.cli.hub.services import HubServices
from stenographer.cli.hub.session_titles import SessionTitles
from stenographer.lib.config.models import Config
from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.refine.errors import RefineTransportError
from stenographer.lib.refine.title import request_title
from stenographer.lib.sessions import SessionStore
from tests.cli.hub.test_library import FakeTitleRequest

STARTED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
SECRET = "zebracorn marmalade"
TITLE = "Quokka budget, lantern repairs"
MODEL = "gemma4:e2b"


def _session(tmp_path, minute: int, text: str | None = SECRET) -> str:
    writer = SessionWriter.open(tmp_path, STARTED + timedelta(minutes=minute))
    if text is not None:
        writer.append_line(TranscriptLine(0.0, 1.0, "", "mic", "you", "You", text))
    writer.close()
    return writer.path.name


class Harness:
    def __init__(self, tmp_path, *, enabled=True, installed=True, reply=TITLE, request=None):
        self.store = SessionStore(tmp_path / "sessions")
        defaults = Config.defaults()
        self.config = replace(defaults, refine=replace(defaults.refine, enabled=enabled))
        self.request = FakeTitleRequest(reply) if request is None else request
        self.installed_calls: list[tuple[str, str]] = []
        self.installed = installed
        self.titles = SessionTitles(
            lambda: self.store,
            lambda: self.config,
            request=self.request,
            installed=self._installed,
        )
        self.sentinel = _session(tmp_path, 59, text="sentinel words")

    def _installed(self, host, model):
        self.installed_calls.append((host, model))
        return self.installed

    def drain(self) -> None:
        """Queue ``g`` on the sentinel session and wait until it ends: the worker is FIFO."""
        assert self.titles.generate(self.sentinel)
        _wait(lambda: self.sentinel not in self.titles.generating)

    def requests_for(self, needle: str) -> list[tuple]:
        return [call for call in self.request.calls if needle in call[2]]

    def title(self, session_id: str) -> tuple[str | None, str | None]:
        summary = self.store.read(session_id).summary
        return summary.title, summary.title_source


def _wait(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met")
        time.sleep(0.005)


# Automatic titles


def test_an_automatic_title_is_stored_with_source_model(tmp_path):
    harness = Harness(tmp_path)
    session = _session(tmp_path, 0)
    harness.titles.generate_auto(session)
    harness.drain()
    assert harness.title(session) == (TITLE, "model")
    [(host, model, text, keep_alive)] = harness.requests_for(SECRET)
    assert (host, model) == ("http://127.0.0.1:11434", MODEL)
    assert text == f"You: {SECRET}"
    # The refine keep_alive: the idle unload time of the speech model.
    assert keep_alive == harness.config.asr.idle_unload_seconds
    assert harness.installed_calls == [("http://127.0.0.1:11434", MODEL)]


@pytest.mark.parametrize("enabled, installed", [(False, True), (True, False)])
def test_no_automatic_request_when_refine_is_off_or_its_model_is_not_installed(
    tmp_path, enabled, installed
):
    harness = Harness(tmp_path, enabled=enabled, installed=installed)
    session = _session(tmp_path, 0)
    harness.titles.generate_auto(session)
    harness.drain()
    assert harness.requests_for(SECRET) == []
    assert harness.title(session) == (None, None)


@pytest.mark.parametrize("source", ["user", "model"])
def test_no_automatic_request_for_a_session_that_has_a_title(tmp_path, source):
    harness = Harness(tmp_path)
    session = _session(tmp_path, 0)
    harness.store.set_title(session, "Typed before", source=source)
    harness.titles.generate_auto(session)
    harness.drain()
    assert harness.requests_for(SECRET) == []
    assert harness.title(session) == ("Typed before", source)


def test_an_automatic_title_never_replaces_a_title_typed_during_the_request(tmp_path):
    harness = Harness(tmp_path)
    harness.request.release.clear()
    session = _session(tmp_path, 0)
    harness.titles.generate_auto(session)
    assert harness.request.started.wait(5)
    assert session in harness.titles.generating
    harness.store.set_title(session, "Typed meanwhile")
    harness.request.release.set()
    harness.drain()
    assert harness.title(session) == ("Typed meanwhile", "user")


def test_an_empty_transcript_gets_no_request(tmp_path):
    harness = Harness(tmp_path)
    session = _session(tmp_path, 0, text=None)
    harness.titles.generate_auto(session)
    harness.drain()
    assert harness.titles.generate(session)
    harness.drain()
    assert [call[2] for call in harness.request.calls] == ["You: sentinel words"] * 2
    assert harness.titles.take_notices() == [("This session has no transcript lines.", "warning")]


def test_an_automatic_failure_logs_one_warning_and_leaves_no_title(tmp_path, caplog):
    harness = Harness(tmp_path, reply=RefineTransportError("ollama could not be reached"))
    session = _session(tmp_path, 0)
    caplog.set_level(logging.DEBUG)
    harness.titles.generate_auto(session)
    _wait(lambda: harness.requests_for(SECRET) and session not in harness.titles.generating)
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "title_failed" in warnings[0].getMessage()
    assert harness.title(session) == (None, None)
    assert harness.titles.take_notices() == []


# g


def test_g_stores_a_model_title_over_no_title_and_over_a_model_title(tmp_path):
    harness = Harness(tmp_path)
    untitled = _session(tmp_path, 0)
    titled = _session(tmp_path, 1)
    harness.store.set_title(titled, "Old model title", source="model")
    assert harness.titles.generate(untitled)
    assert harness.titles.generate(titled)
    harness.drain()
    assert harness.title(untitled) == (TITLE, "model")
    assert harness.title(titled) == (TITLE, "model")


def test_g_replaces_the_typed_title_that_the_user_agreed_to_replace_and_no_other(tmp_path):
    harness = Harness(tmp_path)
    agreed = _session(tmp_path, 0)
    changed = _session(tmp_path, 1)
    harness.store.set_title(agreed, "Typed")
    harness.store.set_title(changed, "Typed again elsewhere")
    assert harness.titles.generate(agreed, replace="Typed")
    assert harness.titles.generate(changed, replace="Typed")
    harness.drain()
    assert harness.title(agreed) == (TITLE, "model")
    assert harness.title(changed) == ("Typed again elsewhere", "user")


def test_a_session_generates_once_at_a_time_and_g_wins_over_its_automatic_title(tmp_path):
    harness = Harness(tmp_path)
    harness.request.release.clear()
    session = _session(tmp_path, 0)
    assert harness.titles.generate(session)
    assert not harness.titles.generate(session)
    # The automatic title waits behind g and then finds g's title: no second request.
    harness.titles.generate_auto(session)
    harness.request.release.set()
    harness.drain()
    assert len(harness.requests_for(SECRET)) == 1
    assert harness.title(session) == (TITLE, "model")


def test_a_session_deleted_during_the_request_drops_the_result_without_a_notice(tmp_path, caplog):
    harness = Harness(tmp_path)
    harness.request.release.clear()
    session = _session(tmp_path, 0)
    folder = harness.store.root / session
    caplog.set_level(logging.DEBUG)
    assert harness.titles.generate(session)
    assert harness.request.started.wait(5)
    harness.store.delete(session)
    harness.request.release.set()
    harness.drain()
    assert not folder.exists()
    assert harness.titles.take_notices() == []
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_a_failure_of_g_gives_a_notice_with_the_reason(tmp_path):
    harness = Harness(tmp_path, reply=RefineTransportError("ollama could not be reached"))
    session = _session(tmp_path, 0)
    assert harness.titles.generate(session)
    _wait(lambda: session not in harness.titles.generating)
    assert harness.titles.take_notices() == [
        ("Could not generate a title: ollama could not be reached.", "error")
    ]
    assert harness.title(session) == (None, None)


def test_the_worker_keeps_working_after_a_config_that_cannot_be_read(tmp_path, caplog):
    harness = Harness(tmp_path)
    good = harness.config
    session = _session(tmp_path, 0)
    harness.config = None
    caplog.set_level(logging.WARNING)
    harness.titles.generate_auto(session)
    _wait(lambda: any("title_failed" in record.getMessage() for record in caplog.records))
    harness.config = good
    harness.drain()
    assert harness.requests_for("sentinel")


# Privacy


def _reply(content: str) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}}).encode()


@pytest.mark.parametrize("run", ["g", "auto", "failed-g", "failed-auto"])
def test_no_title_and_no_transcript_text_in_the_debug_log(tmp_path, caplog, run):
    failed = run.startswith("failed")
    # The real request with a fake post: a failed run gets two lines that quote the transcript.
    reply = f"{SECRET}\n{TITLE}" if failed else TITLE
    harness = Harness(
        tmp_path,
        request=lambda host, model, text, *, keep_alive: request_title(
            host, model, text, keep_alive=keep_alive, post=lambda *_a, **_k: _reply(reply)
        ),
    )
    session = _session(tmp_path, 0)
    caplog.set_level(logging.DEBUG)
    if run.endswith("g"):
        assert harness.titles.generate(session)
    else:
        harness.titles.generate_auto(session)
    harness.drain()
    text = "\n".join(record.getMessage() for record in caplog.records)
    # The log has the events of the run: the capture works.
    assert ("title_failed" if failed else "title_saved") in text
    for content in (SECRET, "zebracorn", "marmalade", TITLE, "Quokka", "sentinel words"):
        assert content not in text
    for record in caplog.records:
        if record.exc_info:
            assert SECRET not in str(record.exc_info[1])
    assert harness.title(session) == ((None, None) if failed else (TITLE, "model"))


def test_a_saved_recording_queues_its_title_and_the_save_does_not_wait_for_the_model(tmp_path):
    harness = Harness(tmp_path)
    harness.request.release.clear()
    folders = iter(harness.store.root / _session(tmp_path, minute) for minute in (0, 1))

    class Recording:
        def __init__(self, _config, **_kwargs):
            self.path = next(folders)

        def start(self):
            pass

        def stop(self):
            pass

    services = HubServices(harness.config, object(), session_factory=Recording)
    services._titles = harness.titles
    services.start_recording()
    first = services.begin_stop()
    services.finish_stop(first)
    assert harness.request.started.wait(5)
    # The model holds the first title; the second save still returns at once.
    services.start_recording()
    second = services.begin_stop()
    services.finish_stop(second)
    assert not harness.request.release.is_set()
    harness.request.release.set()
    harness.drain()
    assert harness.title(first.path.name) == (TITLE, "model")
    assert harness.title(second.path.name) == (TITLE, "model")


@pytest.mark.parametrize("manual", [True, False], ids=["g", "auto"])
def test_an_unexpected_error_that_quotes_the_transcript_stays_out_of_the_log(
    tmp_path, caplog, manual
):
    def request(host, model, text, *, keep_alive):
        raise ValueError(f"cannot parse {text}")

    harness = Harness(tmp_path, request=request)
    session = _session(tmp_path, 0)
    caplog.set_level(logging.DEBUG)
    if manual:
        assert harness.titles.generate(session)
    else:
        harness.titles.generate_auto(session)
    _wait(lambda: any("title_failed" in record.getMessage() for record in caplog.records))
    _wait(lambda: session not in harness.titles.generating)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "ValueError" in text
    assert "zebracorn" not in text
    assert all(record.exc_info is None for record in caplog.records)
    notices = harness.titles.take_notices()
    assert notices == ([("Could not generate a title.", "error")] if manual else [])
