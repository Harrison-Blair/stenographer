# SPDX-License-Identifier: GPL-3.0-or-later
"""A live source that stops delivering audio: the pure watch and the session report."""

from __future__ import annotations

import logging
import time

import pytest

from stenographer.lib.live.source_watch import SILENT_SECONDS, SourceWatch
from stenographer.lib.platform.errors import MicCaptureError
from tests.lib.live.test_live_session import FakeClock, _make_session


def test_a_source_is_silent_after_five_seconds_without_a_block():
    watch = SourceWatch()
    watch.started("mic", 100.0)
    watch.started("system", 100.0)
    watch.block("system", 104.0)

    assert watch.silent(104.9) == ()
    assert watch.silent(105.0) == ("mic",)
    assert watch.silent(109.0) == ("mic", "system")


def test_check_reports_each_change_once():
    watch = SourceWatch()
    watch.started("mic", 0.0)

    assert watch.check(4.0) == ((), ())
    assert watch.check(5.0) == (("mic",), ())
    assert watch.check(9.0) == ((), ())
    watch.block("mic", 9.5)
    assert watch.check(10.0) == ((), ("mic",))
    assert watch.check(11.0) == ((), ())
    assert watch.check(14.5) == (("mic",), ())


def test_a_stopped_source_is_never_silent_and_a_block_does_not_start_it():
    watch = SourceWatch()
    watch.started("mic", 0.0)
    watch.check(SILENT_SECONDS)
    watch.stopped("mic")
    watch.block("mic", 1.0)

    assert watch.silent(100.0) == ()
    assert watch.check(100.0) == ((), ())


def test_the_session_shows_a_silent_source_until_audio_returns(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    try:
        rig.recorder.emit(1)
        rig.system.emit(1)
        clock.now = 4.0
        rig.system.emit(1)
        clock.now = 5.0

        assert rig.session.silent_sources == ("mic",)

        rig.recorder.emit(1)
        assert rig.session.silent_sources == ()
        assert rig.recorder.running
    finally:
        rig.session.stop()


def test_a_paused_session_has_no_silent_source(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    try:
        rig.session.pause()
        clock.now = 60.0

        assert rig.session.silent_sources == ()
    finally:
        rig.session.stop()


def test_the_session_logs_one_warning_and_the_return(monkeypatch, tmp_path, caplog):
    import stenographer.lib.live.live_session as live_session

    monkeypatch.setattr(live_session, "_WATCH_INTERVAL_SECONDS", 0.01)
    clock = FakeClock()
    with caplog.at_level(logging.INFO, logger="stenographer.lib.live.live_session"):
        rig = _make_session(monkeypatch, tmp_path, clock=clock, system=False)
        try:
            clock.now = 6.0
            _wait_for(lambda: "live: source_silent" in caplog.text)
            time.sleep(0.05)
            rig.recorder.emit(1)
            _wait_for(lambda: "live: source_resumed" in caplog.text)
        finally:
            rig.session.stop()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == ["live: source_silent source=mic seconds=5"]


def test_a_mic_capture_failure_turns_the_mic_off_and_keeps_system(monkeypatch, tmp_path, caplog):
    rig = _make_session(monkeypatch, tmp_path)
    try:
        with caplog.at_level(logging.WARNING, logger="stenographer.lib.live.live_session"):
            rig.recorder.on_block(MicCaptureError("pw-record exited unexpectedly with status 1"))

        assert rig.session.source_states == {"mic": "off", "system": "on"}
        assert "live: mic_source_failed" in caplog.text
        assert rig.session.silent_sources == ()
    finally:
        rig.session.stop()


def _wait_for(condition) -> None:
    deadline = time.monotonic() + 2
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


@pytest.mark.parametrize("source", ["mic", "system"])
def test_a_source_that_fails_before_start_returns_is_not_watched(monkeypatch, tmp_path, source):
    from stenographer.lib.platform.errors import SystemAudioCaptureError

    clock = FakeClock()
    rig = _make_session(
        monkeypatch,
        tmp_path,
        clock=clock,
        mic=source == "mic",
        system=source == "system",
        start=False,
    )
    if source == "mic":
        rig.recorder.start = lambda target, on_block: on_block(MicCaptureError("pw-record exited"))
    else:
        rig.system.start = lambda on_block: on_block(SystemAudioCaptureError("pw-record exited"))
    try:
        rig.session.start()
        assert rig.session.source_states[source] == "off"
        clock.now = 6.0

        assert rig.session.silent_sources == ()
    finally:
        rig.session.stop()


def _record_warnings(session) -> list[str]:
    """The warning items that Record's speaker bar shows for *session*."""
    from types import SimpleNamespace

    from stenographer.cli.hub.record_screen import RecordScreen

    screen = SimpleNamespace(_rename_busy=lambda _session: False)
    items = RecordScreen._speaker_items(screen, session, (), ())
    return [item.plain for item in items if item.plain.startswith("!")]


def _fail(rig, source: str) -> None:
    from stenographer.lib.platform.errors import SystemAudioCaptureError

    if source == "mic":
        rig.recorder.on_block(MicCaptureError("pw-record exited unexpectedly with status 1"))
    else:
        rig.system.on_block(SystemAudioCaptureError("pw-record exited unexpectedly with status 1"))


@pytest.mark.parametrize("source", ["mic", "system"])
def test_record_shows_a_source_whose_capture_fails_as_stopped(monkeypatch, tmp_path, source):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    try:
        _fail(rig, source)
        clock.now = 6.0  # past the silence time: stopped only, never also no audio

        assert rig.session.source_states[source] == "off"
        warnings = [text for text in _record_warnings(rig.session) if f" {source} " in text]
        assert warnings == [f"! {source} stopped"]
    finally:
        rig.session.stop()
    assert _record_warnings(rig.session) == []


@pytest.mark.parametrize("source", ["mic", "system"])
def test_record_shows_a_source_that_fails_before_start_returns_as_stopped(
    monkeypatch, tmp_path, source
):
    from stenographer.lib.platform.errors import SystemAudioCaptureError

    rig = _make_session(monkeypatch, tmp_path, start=False)
    if source == "mic":
        rig.recorder.start = lambda target, on_block: on_block(MicCaptureError("pw-record exited"))
    else:
        rig.system.start = lambda on_block: on_block(SystemAudioCaptureError("pw-record exited"))
    try:
        rig.session.start()
        assert _record_warnings(rig.session) == [f"! {source} stopped"]
    finally:
        rig.session.stop()


def test_a_source_the_user_turns_off_shows_no_warning(monkeypatch, tmp_path):
    clock = FakeClock()
    rig = _make_session(monkeypatch, tmp_path, clock=clock)
    try:
        rig.session.toggle("mic")
        clock.now = 6.0
        assert rig.session.source_states["mic"] == "off"
        assert [text for text in _record_warnings(rig.session) if " mic " in text] == []
    finally:
        rig.session.stop()


def test_the_stopped_warning_ends_when_the_user_turns_the_source_on_again(monkeypatch, tmp_path):
    rig = _make_session(monkeypatch, tmp_path)
    try:
        _fail(rig, "mic")
        assert _record_warnings(rig.session) == ["! mic stopped"]

        rig.session.toggle("mic")

        assert rig.session.source_states["mic"] == "on"
        assert _record_warnings(rig.session) == []
    finally:
        rig.session.stop()
