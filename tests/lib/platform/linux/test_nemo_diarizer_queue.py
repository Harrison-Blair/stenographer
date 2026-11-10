# SPDX-License-Identifier: GPL-3.0-or-later
"""Live streams bound the audio a slow helper has not handled yet."""

from __future__ import annotations

import numpy as np

from stenographer.lib.platform.linux.nemo_diarizer import NemoSpeakerDiarizer
from stenographer.lib.platform.speaker_diarizer import LIVE_QUEUE_SECONDS, SAMPLE_RATE
from tests.lib.platform.linux.slow_diarizer_child import quick_child, slow_child

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
            assert stream.poll() == ((), ())
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
