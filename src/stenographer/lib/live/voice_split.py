# SPDX-License-Identifier: GPL-3.0-or-later
"""Group the phrases of one source and split long phrases at clear voice changes."""

from __future__ import annotations

import contextlib
import itertools
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.live.relabel import relabel_system_lines
from stenographer.lib.live.speaker_tracker import MINIMUM_SPEECH_DURATION_SECONDS
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event

log = logging.getLogger(__name__)

# The user tested these four settings by ear on saved sessions.
_MINIMUM_PHRASE_SECONDS = 6.0
_SLICE_SAMPLES = 3 * SAMPLE_RATE
_HOP_SAMPLES = 3 * SAMPLE_RATE // 2
_MINIMUM_LEAD = 0.15
_RUN_SLICES = 2
# A window this long finds a pause between speakers, not a stop consonant inside a word.
_QUIET_WINDOW_SAMPLES = SAMPLE_RATE // 5
# Shares of the progress of one pass. Decoding is the slow part of the pass.
_GROUPED_SHARE = 0.1
_CHECKED_SHARE = 0.95


@dataclass(frozen=True)
class GroupedLines:
    """Grouped lines in time order. ``parents[i]`` is the input line that holds ``lines[i]``."""

    lines: tuple[TranscriptLine, ...]
    parents: tuple[int, ...]


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
    return np.ascontiguousarray(np.mean(samples, axis=1, dtype=np.float32))


def source_segments(
    chunks: Iterator[np.ndarray], lines: Sequence[TranscriptLine]
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield the index and samples of each timed line in one pass over the decoded chunks.

    The lines must be in order of start, so a later line never needs a dropped sample.
    """
    buffer = np.empty(0, dtype=np.float32)
    buffer_start = 0
    for index, line in enumerate(lines):
        if line.end <= line.start:
            continue
        start = max(0, int(line.start * SAMPLE_RATE))
        end = max(start, int(line.end * SAMPLE_RATE))
        while buffer_start + buffer.size < end and (chunk := next(chunks, None)) is not None:
            dropped = min(buffer.size, start - buffer_start)
            buffer = np.concatenate((buffer[dropped:], chunk))
            buffer_start += dropped
        samples = buffer[start - buffer_start : end - buffer_start]
        if samples.size == 0:
            raise ValueError("file session phrase has no audio")
        yield index, samples
    # A decode error after the last line still fails the job.
    for _ in chunks:
        pass


def average_voices(
    lines: Sequence[TranscriptLine], embeddings: Sequence[np.ndarray]
) -> dict[str, np.ndarray]:
    """Return the unit-length, duration-weighted mean voice of each grouped speaker."""
    members: dict[str, list[tuple[np.ndarray, float]]] = {}
    for line, embedding in zip(lines, embeddings, strict=True):
        duration = line.end - line.start
        if duration >= MINIMUM_SPEECH_DURATION_SECONDS:
            vector = np.asarray(embedding, dtype=np.float64)
            members.setdefault(line.speaker_id, []).append(
                (vector / np.linalg.norm(vector), duration)
            )
    voices = {}
    for speaker_id, weighted in members.items():
        mean = np.average(
            [vector for vector, _ in weighted],
            axis=0,
            weights=[duration for _, duration in weighted],
        )
        voices[speaker_id] = mean / np.linalg.norm(mean)
    return voices


def voice_change_cuts(
    samples: np.ndarray,
    speaker_id: str,
    voices: Mapping[str, np.ndarray],
    embed: Callable[[np.ndarray], np.ndarray],
) -> tuple[int, ...]:
    """Return the sample index of each cut of a phrase grouped under *speaker_id*.

    Each slice names the speaker that leads the runner-up by the minimum lead, or nobody.
    The phrase has a voice change when another speaker leads two slices in a row. Each
    cut falls between the centers of two slices, so each part has at least one hop.
    """
    if len(voices) < 2:
        return ()
    names = tuple(voices)
    matrix = np.stack([voices[name] for name in names])
    leaders: list[str | None] = []
    for start in range(0, samples.size - _SLICE_SAMPLES + 1, _HOP_SAMPLES):
        vector = np.asarray(embed(samples[start : start + _SLICE_SAMPLES]), dtype=np.float64)
        scores = matrix @ (vector / np.linalg.norm(vector))
        runner_up, leader = np.argsort(scores)[-2:]
        leaders.append(
            names[leader] if scores[leader] - scores[runner_up] >= _MINIMUM_LEAD else None
        )

    runs = _voice_runs(leaders)
    if not any(speaker != speaker_id for speaker, _, _ in runs):
        return ()
    changes = _change_slices(leaders, runs, speaker_id)
    return tuple(_quietest_sample(samples, *between) for between in changes)


def _voice_runs(leaders: Sequence[str | None]) -> list[tuple[str, int, int]]:
    """Return ``(speaker, first, last)`` of each stretch of one speaker, in slices.

    A stretch starts with a run of two slices. Later runs of the same speaker join it.
    """
    runs: list[tuple[str, int, int]] = []
    index = 0
    while index < len(leaders):
        speaker = leaders[index]
        last = index
        while last + 1 < len(leaders) and leaders[last + 1] == speaker:
            last += 1
        if speaker is not None and last - index + 1 >= _RUN_SLICES:
            if runs and runs[-1][0] == speaker:
                runs[-1] = (speaker, runs[-1][1], last)
            else:
                runs.append((speaker, index, last))
        index = last + 1
    return runs


def _change_slices(
    leaders: Sequence[str | None], runs: Sequence[tuple[str, int, int]], speaker_id: str
) -> list[tuple[int, int]]:
    """Return the two slices that hold each voice change.

    Unclear slices at the ends of a phrase show no change. One clear slice of another
    speaker there ends a run of another voice, but it is no change next to a run of the
    phrase's own speaker, because a change needs two slices in a row.
    """
    changes = []
    speaker, first, _ = runs[0]
    before = [i for i in range(first) if leaders[i] not in (None, speaker)]
    if before and speaker != speaker_id:
        changes.append((before[-1], first))
    changes.extend((left[2], right[1]) for left, right in itertools.pairwise(runs))
    speaker, _, last = runs[-1]
    after = [i for i in range(last + 1, len(leaders)) if leaders[i] not in (None, speaker)]
    if after and speaker != speaker_id:
        changes.append((last, after[0]))
    return changes


def _quietest_sample(samples: np.ndarray, left_slice: int, right_slice: int) -> int:
    """Return the center of the quietest window between the centers of two slices."""
    start = left_slice * _HOP_SAMPLES + _SLICE_SAMPLES // 2
    end = right_slice * _HOP_SAMPLES + _SLICE_SAMPLES // 2
    window_start = start - _QUIET_WINDOW_SAMPLES // 2
    power = np.cumsum(
        np.square(samples[window_start : end + _QUIET_WINDOW_SAMPLES // 2], dtype=np.float64)
    )
    energy = power[_QUIET_WINDOW_SAMPLES:] - power[:-_QUIET_WINDOW_SAMPLES]
    return start + int(np.argmin(energy))


def _shifted_wall(wall: str, seconds: float) -> str:
    # A line of a file job has no wall time.
    if not wall:
        return wall
    return (datetime.fromisoformat(wall) + timedelta(seconds=seconds)).isoformat()


def _split_line(
    line: TranscriptLine,
    samples: np.ndarray,
    cuts: tuple[int, ...],
    decode: Callable[[np.ndarray], str],
    should_cancel: Callable[[], bool],
) -> list[tuple[TranscriptLine, np.ndarray]] | None:
    """Return the parts of a line, or an empty list if a part has no text and the line stays.

    Return ``None`` on a cancel.
    """
    edges = (0, *cuts, samples.size)
    parts = []
    for first, last in itertools.pairwise(edges):
        if should_cancel():
            return None
        text = decode(samples[first:last]).strip()
        if not text:
            return []
        start = line.start + first / SAMPLE_RATE
        parts.append(
            (
                replace(
                    line,
                    start=start,
                    end=line.end if last == samples.size else line.start + last / SAMPLE_RATE,
                    wall=_shifted_wall(line.wall, first / SAMPLE_RATE),
                    text=text,
                ),
                samples[first:last],
            )
        )
    return parts


def group_and_split(
    lines: Sequence[TranscriptLine],
    embeddings: Sequence[np.ndarray],
    *,
    read_audio: Callable[[tuple[TranscriptLine, ...]], Iterator[np.ndarray]] | None,
    embed: Callable[[np.ndarray], np.ndarray],
    decode: Callable[[np.ndarray], str],
    progress: Callable[[float], None] = lambda _fraction: None,
    should_cancel: Callable[[], bool] = lambda: False,
    speaker_count: int | None = None,
    label_prefix: str = "Speaker",
) -> GroupedLines | None:
    """Group one source, split the phrases with a voice change, and group the new lines.

    *read_audio* gets the long lines and yields their samples in that order; ``None`` means
    the source has no saved audio, so no phrase can split. *progress* gets a fraction that
    never falls. Return ``None`` on a cancel.
    """
    original = tuple(lines)
    vectors = tuple(embeddings)

    def stage(start: float, end: float) -> Callable[[int, int], None]:
        # The grouping count can pass its total near the end of a pass.
        return lambda done, total: progress(start + (end - start) * min(done, total) / total)

    grouped = relabel_system_lines(
        original,
        vectors,
        progress=stage(0.0, _GROUPED_SHARE),
        should_cancel=should_cancel,
        speaker_count=speaker_count,
        label_prefix=label_prefix,
    )
    if grouped is None:
        return None
    unchanged = GroupedLines(grouped, tuple(range(len(grouped))))
    voices = average_voices(grouped, vectors)
    long_indices = [
        index
        for index, line in enumerate(grouped)
        if line.end - line.start >= _MINIMUM_PHRASE_SECONDS
    ]
    if read_audio is None or len(voices) < 2 or not long_indices:
        progress(1.0)
        return unchanged

    long_lines = tuple(grouped[index] for index in long_indices)
    total_seconds = sum(line.end - line.start for line in long_lines)
    checked_seconds = 0.0
    splits: dict[int, list[tuple[TranscriptLine, np.ndarray]]] = {}
    with contextlib.closing(read_audio(long_lines)) as segments:
        for index, line, samples in zip(long_indices, long_lines, segments, strict=False):
            if should_cancel():
                return None
            cuts = voice_change_cuts(samples, line.speaker_id, voices, embed)
            if cuts:
                parts = _split_line(line, samples, cuts, decode, should_cancel)
                if parts is None:
                    return None
                if parts:
                    splits[index] = parts
            checked_seconds += line.end - line.start
            progress(
                _GROUPED_SHARE + (_CHECKED_SHARE - _GROUPED_SHARE) * checked_seconds / total_seconds
            )
    if not splits:
        progress(1.0)
        return unchanged

    new_lines: list[TranscriptLine] = []
    new_vectors: list[np.ndarray] = []
    parents: list[int] = []
    for index, (line, vector) in enumerate(zip(grouped, vectors, strict=True)):
        for part, samples in splits.get(index, ()):
            new_lines.append(part)
            new_vectors.append(embed(samples))
            parents.append(index)
        if index not in splits:
            new_lines.append(line)
            new_vectors.append(vector)
            parents.append(index)
    regrouped = relabel_system_lines(
        new_lines,
        new_vectors,
        progress=stage(_CHECKED_SHARE, 1.0),
        should_cancel=should_cancel,
        speaker_count=speaker_count,
        label_prefix=label_prefix,
    )
    if regrouped is None:
        return None
    log.debug(
        fmt_event(
            "live",
            "voice_changes_split",
            phrase_count=len(splits),
            line_count=len(regrouped),
        )
    )
    return GroupedLines(regrouped, tuple(parents))
