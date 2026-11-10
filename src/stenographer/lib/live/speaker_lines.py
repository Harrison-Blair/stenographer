# SPDX-License-Identifier: GPL-3.0-or-later
"""The line rule: a line ends at a pause or where the speaker changes, and has one speaker.

Speaker segments come from ``SpeakerDiarizer``. Live, saved, and file lines share
these rules, so each place labels the same audio the same way.
"""

from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from stenographer.lib.live.transcript_line import TranscriptLine
    from stenographer.lib.platform.speaker_diarizer import SpeakerSegment

# Speaker labels of each source; mic and system speakers never share a number space.
LABEL_PREFIXES = {"system": "Speaker", "mic": "Room", "file": "Speaker"}
# The ``(speaker_id, label)`` of a line with no speaker separation.
NO_SPEAKER = {
    "mic": ("you", "You"),
    "system": ("system", "System"),
    "file": ("speaker-1", "Speaker 1"),
}


@dataclass(frozen=True)
class Piece:
    """A part of a line with one speaker; ``None`` when no segment exists at all."""

    start: float
    end: float
    speaker: int | None


def speaker_pieces(
    start: float, end: float, segments: Sequence[SpeakerSegment]
) -> tuple[Piece, ...]:
    """Cut ``[start, end]`` where the speaker changes. PURE.

    A speaker keeps the time while their segment lasts, so overlapping speech stays
    with whoever spoke first. Time that no segment covers joins the piece before it,
    or the piece after it at the start. With no segment inside, the whole span goes
    to the speaker of the nearest segment.
    """
    inside = [s for s in segments if s.start < end and s.end > start]
    if not inside:
        if not segments:
            return (Piece(start, end, None),)
        nearest = min(segments, key=lambda s: max(s.start - end, start - s.end))
        return (Piece(start, end, nearest.speaker),)
    edges = sorted({start, end, *(t for s in inside for t in (s.start, s.end) if start < t < end)})
    held: list[list] = []
    current: int | None = None
    for left, right in itertools.pairwise(edges):
        holders = [s for s in inside if s.start <= left and right <= s.end]
        if not holders:
            speaker = None
        elif any(s.speaker == current for s in holders):
            speaker = current
        else:
            speaker = min(holders, key=lambda s: (s.start, s.speaker)).speaker
        if speaker is not None:
            current = speaker
        held.append([left, right, speaker])
    first = next(part[2] for part in held if part[2] is not None)
    previous = first
    for part in held:
        if part[2] is None:
            part[2] = previous
        previous = part[2]
    pieces: list[Piece] = []
    for left, right, speaker in held:
        if pieces and pieces[-1].speaker == speaker:
            pieces[-1] = replace(pieces[-1], end=right)
        else:
            pieces.append(Piece(left, right, speaker))
    return tuple(pieces)


class SpeakerNames:
    """Speaker ids and labels of one source, numbered from 1 by first line."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._prefix = LABEL_PREFIXES[source]
        self._id_prefix = f"{self._prefix.lower()}-"
        self._numbers: dict[int, int] = {}
        self._names: dict[str, str] = {}

    def speaker(self, index: int | None) -> tuple[str, str]:
        """Return ``(speaker_id, label)`` for a diarizer speaker index."""
        if index is None:
            return NO_SPEAKER[self._source]
        number = self._numbers.setdefault(index, len(self._numbers) + 1)
        speaker_id = f"{self._id_prefix}{number}"
        return speaker_id, self.label(speaker_id)

    def label(self, speaker_id: str) -> str:
        number = speaker_id.removeprefix(self._id_prefix)
        return self._names.get(speaker_id, f"{self._prefix} {number}")

    def owns(self, speaker_id: str) -> bool:
        return speaker_id in {f"{self._id_prefix}{n}" for n in self._numbers.values()}

    def checked_label(self, speaker_id: str, name: str) -> str:
        """Return the label for *name*; raise ``ValueError`` if it cannot be set."""
        label = name.strip()
        if not label:
            raise ValueError("Speaker name cannot be empty")
        if not self.owns(speaker_id):
            raise ValueError(f"Unknown speaker ID: {speaker_id}")
        return label

    def rename(self, speaker_id: str, label: str) -> None:
        self._names[speaker_id] = self.checked_label(speaker_id, label)


class StreamClock:
    """Map live-stream seconds to session seconds. A source pushes audio only while it
    runs, so each run starts a new offset."""

    def __init__(self) -> None:
        self._stream_starts: list[float] = []
        self._session_starts: list[float] = []

    def start_run(self, stream_seconds: float, session_seconds: float) -> None:
        self._stream_starts.append(stream_seconds)
        self._session_starts.append(session_seconds)

    def session_time(self, stream_seconds: float) -> float:
        if math.isinf(stream_seconds) or not self._stream_starts:
            return stream_seconds
        run = max(0, bisect.bisect_right(self._stream_starts, stream_seconds) - 1)
        return self._session_starts[run] + stream_seconds - self._stream_starts[run]


def read_saved_audio(path: Path, start: float, end: float) -> np.ndarray:
    """Return mono samples of one interval of a saved 16 kHz session audio file."""
    with sf.SoundFile(path) as audio:
        if audio.samplerate != SAMPLE_RATE:
            raise ValueError(f"session audio must use {SAMPLE_RATE} Hz: {path}")
        first = min(audio.frames, max(0, int(start * audio.samplerate)))
        last = min(audio.frames, max(first, int(end * audio.samplerate)))
        audio.seek(first)
        samples = audio.read(last - first, dtype="float32", always_2d=True)
    if len(samples) == 0:
        raise ValueError(f"session phrase has no audio: {path}")
    mono = samples[:, 0] if samples.shape[1] == 1 else np.mean(samples, axis=1, dtype=np.float32)
    return np.ascontiguousarray(mono)


def given_name(line: TranscriptLine) -> str | None:
    """The name the user gave the speaker of *line*, or ``None`` for a default label."""
    if (line.speaker_id, line.label) in NO_SPEAKER.values():
        return None
    prefix, _, number = line.speaker_id.rpartition("-")
    return None if line.label == f"{prefix.capitalize()} {number}" else line.label


def shifted_wall(wall: str, seconds: float) -> str:
    # A line of a file job has no wall time.
    if not wall:
        return wall
    return (datetime.fromisoformat(wall) + timedelta(seconds=seconds)).isoformat()


def relabel_lines(
    lines: Sequence[TranscriptLine],
    segments: Sequence[SpeakerSegment],
    names: SpeakerNames,
    *,
    read_audio: Callable[[float, float], np.ndarray],
    decode: Callable[[np.ndarray], str],
    decode_all: bool = False,
    progress: Callable[[float], None] = lambda _fraction: None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> list[TranscriptLine] | None:
    """Give the saved lines of one source their speakers by the line rule.

    A line with one speaker keeps its text unless *decode_all*; a line with a speaker
    change is cut there and each part is decoded once. A part with no text is dropped;
    a line whose parts all have no text stays whole with its longest speaker.
    A new speaker keeps the name the user gave to most of its time. Return ``None``
    on a cancel.
    """
    result: list[TranscriptLine] = []
    # Seconds of each new speaker id under each name the user gave.
    named: dict[str, dict[str, float]] = {}
    for done, line in enumerate(lines, 1):
        if should_cancel():
            return None
        first_new = len(result)
        pieces = speaker_pieces(line.start, line.end, segments)
        if len(pieces) == 1 and not decode_all:
            speaker_id, label = names.speaker(pieces[0].speaker)
            result.append(replace(line, speaker_id=speaker_id, label=label))
        else:
            samples = read_audio(line.start, line.end)
            parts = []
            for piece in pieces:
                first = round((piece.start - line.start) * SAMPLE_RATE)
                last = round((piece.end - line.start) * SAMPLE_RATE)
                if last <= first:
                    continue
                text = decode(samples[first:last]).strip()
                if text:
                    parts.append((piece, text))
            if not parts:
                longest = max(pieces, key=lambda piece: piece.end - piece.start)
                speaker_id, label = names.speaker(longest.speaker)
                result.append(
                    replace(
                        line,
                        speaker_id=speaker_id,
                        label=label,
                        text="" if decode_all else line.text,
                    )
                )
            for piece, text in parts:
                speaker_id, label = names.speaker(piece.speaker)
                result.append(
                    replace(
                        line,
                        start=piece.start,
                        end=piece.end,
                        wall=shifted_wall(line.wall, piece.start - line.start),
                        speaker_id=speaker_id,
                        label=label,
                        text=text,
                    )
                )
        name = given_name(line)
        for kept in result[first_new:]:
            if name is not None and names.owns(kept.speaker_id):
                time = named.setdefault(kept.speaker_id, {})
                time[name] = time.get(name, 0.0) + kept.end - kept.start
        progress(done / max(1, len(lines)))
    for speaker_id, time in named.items():
        names.rename(speaker_id, max(time, key=time.__getitem__))
    return [
        replace(line, label=names.label(line.speaker_id)) if names.owns(line.speaker_id) else line
        for line in result
        if line.text
    ]
