# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaker separation: who spoke when, for a saved file or a live stream.

Speakers are numbered per file or per live stream, from 0, in order of first
appearance. Two streams never share speaker numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import numpy as np

# Audio pushed into a live stream: mono float32 at this rate.
SAMPLE_RATE = 16_000
# CPU threads of one helper, shared by all its streams. Measured: the live preset
# keeps up with a mic and a system stream at once at RTF 0.40 (about 1.6 cores busy).
THREADS = 4
# A live stream holds at most this much audio that the helper has not handled.
LIVE_QUEUE_SECONDS = 60.0

# A segment is final when it ends this far before the labelled edge. The library
# changes only the segment open at the edge: its end can move by the gap fill
# (0.296 s) and the pads (0.229 s + 0.079 s). The rest is margin.
FINAL_LAG_SECONDS = 0.296 + 0.229 + 0.079 + 0.2


@dataclass(frozen=True)
class SpeakerSegment:
    speaker: int
    start: float
    end: float


@dataclass(frozen=True)
class LivePoll:
    """One consistent view of a live stream: the segments that became final since
    the last poll, the open segments at the live edge, and the stream seconds up to
    which every segment is final (``-inf`` at first, ``inf`` after ``finish``)."""

    final: tuple[SpeakerSegment, ...]
    tail: tuple[SpeakerSegment, ...]
    final_until: float


def split_final(
    segments: Sequence[SpeakerSegment], edge: float, final_until: float
) -> tuple[tuple[SpeakerSegment, ...], tuple[SpeakerSegment, ...], float]:
    """Split a stream's segments at its labelled *edge* (seconds). PURE.

    Return ``(new_final, tail, final_until)``. ``new_final`` holds the segments
    that became final since the call that returned *final_until*; ``tail`` holds
    the segments that can still change. ``edge = math.inf`` finalizes all.
    """
    horizon = edge - FINAL_LAG_SECONDS
    new_final = tuple(s for s in segments if final_until < s.end <= horizon)
    tail = tuple(s for s in segments if s.end > horizon)
    return new_final, tail, max(final_until, horizon)


def finalize_all(
    segments: Sequence[SpeakerSegment], final_until: float
) -> tuple[SpeakerSegment, ...]:
    """The segments not yet final when a stream ends. PURE."""
    return split_final(segments, math.inf, final_until)[0]


class LiveDiarization(Protocol):
    """One live stream of one audio source.

    When the helper falls behind by more than ``LIVE_QUEUE_SECONDS`` of audio,
    the stream overflows: its queued audio is released and it gives no more
    labels. ``overflowed()`` then stays true, ``push`` does nothing, ``poll``
    returns only the finals received before, and ``finish`` returns at once.
    """

    def push(self, samples: np.ndarray) -> None:
        """Queue mono float32 audio at ``SAMPLE_RATE``. Does not block."""
        ...

    def overflowed(self) -> bool:
        """True once the stream fell too far behind and stopped labelling."""
        ...

    def poll(self) -> LivePoll:
        """Return one consistent view of the stream; stream seconds count the audio
        pushed.

        Raise ``SpeakerDiarizerError`` when the stream failed.
        """
        ...

    def finish(self, timeout: float) -> tuple[SpeakerSegment, ...]:
        """Label the queued audio and return all segments not yet returned as final."""
        ...

    def close(self) -> None: ...


class SpeakerDiarizer(Protocol):
    """Speaker separation in a helper process, started on first use."""

    def unavailable_reason(self) -> str | None:
        """Why this host cannot separate speakers, or ``None``. Loads nothing."""
        ...

    def diarize_file(
        self,
        source: Path | np.ndarray,
        *,
        progress: Callable[[float], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[SpeakerSegment, ...] | None:
        """Segments of a sound file or of mono float32 samples at ``SAMPLE_RATE``,
        sorted by start. ``None`` on a cancel.

        Raise ``SpeakerDiarizerError`` when the helper fails.
        """
        ...

    def open_live(self, source: str) -> LiveDiarization:
        """Open a live stream; *source* names it in errors (``mic``, ``system``)."""
        ...

    def close(self) -> None:
        """Stop the helper process. Open streams fail afterwards."""
        ...
