# SPDX-License-Identifier: GPL-3.0-or-later
"""Live streams bound the audio a slow helper has not handled yet."""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np

from stenographer.lib.platform.linux.nemo_diarizer import NemoSpeakerDiarizer
from stenographer.lib.platform.speaker_diarizer import LIVE_QUEUE_SECONDS, SAMPLE_RATE
from tests.lib.platform.linux.slow_diarizer_child import (
    LOG_ENV,
    quick_child,
    recording_slow_child,
    slow_child,
)

BLOCK = np.zeros(SAMPLE_RATE // 10, np.float32)


class _AvailableDiarizer(NemoSpeakerDiarizer):
    def unavailable_reason(self) -> str | None:
        return None


def test_slow_helper_overflows_both_live_streams_with_bounded_queue() -> None:
    diarizer = _AvailableDiarizer(child=slow_child)
    try:
        streams = {"mic": diarizer.open_live("mic"), "system": diarizer.open_live("system")}
        most_queued = 0.0
        for _ in range(1000):  # 100 s of audio per stream, pushed at once
            for stream in streams.values():
                stream.push(BLOCK)
                most_queued = max(most_queued, stream.queued_seconds)

        assert most_queued <= LIVE_QUEUE_SECONDS
        for stream in streams.values():
            assert stream.overflowed()
            assert stream.queued_seconds == 0.0
            view = stream.poll()
            assert (view.final, view.tail) == ((), ())
            assert stream.finish(timeout=1) == ()
        assert diarizer.queued_pushes(0) == 0
        assert diarizer.queued_pushes(1) == 0
    finally:
        diarizer.close()


def test_helper_that_keeps_up_never_overflows() -> None:
    diarizer = _AvailableDiarizer(child=quick_child)
    try:
        stream = diarizer.open_live("mic")
        for second in range(120):
            for _ in range(10):
                stream.push(BLOCK)
            if second % 10 == 9:
                assert stream.wait_replies(lambda: False)

        assert not stream.overflowed()
        assert stream.finish(timeout=5) == ()
    finally:
        diarizer.close()


# The OS pipe and the push being handled hold a few pushes that were sent before a
# close; nothing queued in the parent may follow them.
_IN_PIPE = 15


def _received(log: Path) -> list[tuple[str, int]]:
    return [
        (kind, int(sid))
        for kind, sid in (line.split() for line in log.read_text().split("\n") if line)
    ]


def _recording_diarizer(monkeypatch, tmp_path: Path) -> tuple[NemoSpeakerDiarizer, Path]:
    log = tmp_path / "helper.log"
    monkeypatch.setenv(LOG_ENV, str(log))
    return _AvailableDiarizer(child=recording_slow_child), log


def test_closing_a_behind_stream_drops_its_queue_ahead_of_the_other(
    monkeypatch, tmp_path: Path
) -> None:
    diarizer, log = _recording_diarizer(monkeypatch, tmp_path)
    try:
        mic = diarizer.open_live("mic")
        system = diarizer.open_live("system")
        for _ in range(200):  # 20 s, under the bound, far behind the slow helper
            mic.push(BLOCK)
        mic.close()

        assert diarizer.queued_pushes(0) == 0
        system.push(BLOCK)
        assert system.wait_replies(lambda: False)
        received = _received(log)
        system_at = received.index(("push", 1))
        assert (
            sum(1 for kind, sid in received[:system_at] if (kind, sid) == ("push", 0)) <= _IN_PIPE
        )
    finally:
        diarizer.close()


def test_two_behind_streams_are_sent_in_turn(monkeypatch, tmp_path: Path) -> None:
    diarizer, log = _recording_diarizer(monkeypatch, tmp_path)
    try:
        mic = diarizer.open_live("mic")
        system = diarizer.open_live("system")
        for _ in range(60):
            mic.push(BLOCK)
        for _ in range(60):
            system.push(BLOCK)
        assert mic.wait_replies(lambda: False)
        assert system.wait_replies(lambda: False)

        pushes = [sid for kind, sid in _received(log) if kind == "push"]
        both_queued = pushes[_IN_PIPE : _IN_PIPE + 60]
        assert all(a != b for a, b in itertools.pairwise(both_queued))
    finally:
        diarizer.close()


class _Owner:
    def send(self, _message) -> None:
        pass

    def forget(self, _sid) -> None:
        pass


def test_poll_gives_the_finals_tail_and_final_edge_of_one_update() -> None:
    from stenographer.lib.platform.linux.nemo_diarizer import _Stream
    from stenographer.lib.platform.speaker_diarizer import LivePoll, SpeakerSegment

    stream = _Stream(_Owner(), 0, "mic")
    stream.push(BLOCK)
    final, tail = (SpeakerSegment(0, 0.0, 1.0),), (SpeakerSegment(1, 1.0, 2.5),)
    stream.on_message(("update", 0, final, tail, 1.7))

    assert stream.poll() == LivePoll(final, tail, 1.7)
    assert stream.poll() == LivePoll((), tail, 1.7)
