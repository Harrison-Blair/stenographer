# SPDX-License-Identifier: GPL-3.0-or-later
"""Give the saved lines of one source their speakers from pieces of speech and split lines."""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.live.relabel import apply_cluster_labels, relabel_system_lines
from stenographer.lib.live.speech_pieces import find_speech_pieces
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event

log = logging.getLogger(__name__)

# The user tested this limit on the pieces of saved sessions with the WeSpeaker model.
_GROUPING_THRESHOLD = 0.45
# A shorter hold of another voice does not cut a line.
_MINIMUM_RUN_SECONDS = 1.0
# Shares of the progress of one pass. The pass over the source is the slow part.
_FOUND_SHARE = 0.6
_EMBEDDED_SHARE = 0.8
_GROUPED_SHARE = 0.85


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
    # A long source is about 1 GB, so mono audio is not copied.
    mono = samples[:, 0] if samples.shape[1] == 1 else np.mean(samples, axis=1, dtype=np.float32)
    return np.ascontiguousarray(mono)


def read_saved_source(path: Path) -> np.ndarray:
    """Return mono samples of a whole saved 16 kHz session audio file."""
    return read_saved_audio(path, 0.0, sf.info(path).duration)


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
        vector = np.asarray(embedding, dtype=np.float64)
        members.setdefault(line.speaker_id, []).append(
            (vector / np.linalg.norm(vector), line.end - line.start)
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


def _closest_voice(vector: np.ndarray, voices: dict[str, np.ndarray]) -> str:
    unit = np.asarray(vector, dtype=np.float64) / np.linalg.norm(vector)
    return max(voices, key=lambda speaker_id: float(voices[speaker_id] @ unit))


def _joined_runs(runs: Iterable[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    joined: list[tuple[str, float, float]] = []
    for speaker_id, start, end in runs:
        if joined and joined[-1][0] == speaker_id:
            joined[-1] = (speaker_id, joined[-1][1], end)
        else:
            joined.append((speaker_id, start, end))
    return joined


def _voice_runs(
    spans: Sequence[tuple[float, float, str]], line_start: float, line_end: float
) -> list[tuple[str, float, float]]:
    """Return ``(speaker, start, end)`` of each run of one voice in a line, in time order.

    *spans* are the whole pieces that the line overlaps, by start. Where pieces overlap, the
    voice whose piece started last holds the time, also if it started before the line, so a
    voice that speaks over another gets its own run and the other voice continues after it.
    """
    edges = {line_start, line_end}
    edges.update(
        edge for start, end, _ in spans for edge in (start, end) if line_start < edge < line_end
    )
    held: list[tuple[str, float, float]] = []
    for left, right in itertools.pairwise(sorted(edges)):
        holders = [span for span in spans if span[0] <= left and right <= span[1]]
        if holders:
            held.append((max(holders, key=lambda span: span[0])[2], left, right))
    long_runs = (run for run in _joined_runs(held) if run[2] - run[1] >= _MINIMUM_RUN_SECONDS)
    return _joined_runs(long_runs)


def _line_speech(
    line: TranscriptLine, pieces: Sequence[TranscriptLine]
) -> tuple[dict[str, float], list[tuple[str, float, float]]]:
    """Return the seconds of each speaker that overlap a line, and the voice runs of the line."""
    starts = np.array([piece.start for piece in pieces])
    ends = np.array([piece.end for piece in pieces])
    overlaps = np.minimum(ends, line.end) - np.maximum(starts, line.start)
    shares: dict[str, float] = {}
    spans = []
    for index in np.flatnonzero(overlaps > 0):
        piece = pieces[index]
        shares[piece.speaker_id] = shares.get(piece.speaker_id, 0.0) + float(overlaps[index])
        # A voice with less overlap neither cuts the line nor takes time from a longer voice.
        if overlaps[index] >= _MINIMUM_RUN_SECONDS:
            spans.append((piece.start, piece.end, piece.speaker_id))
    return shares, _voice_runs(spans, line.start, line.end)


def _cuts(line: TranscriptLine, runs: Sequence[tuple[str, float, float]]) -> list[int]:
    """Return the sample index in the line of the middle of the gap between each two runs."""
    return [
        round(((left[2] + right[1]) / 2 - line.start) * SAMPLE_RATE)
        for left, right in itertools.pairwise(runs)
    ]


def _shifted_wall(wall: str, seconds: float) -> str:
    # A line of a file job has no wall time.
    if not wall:
        return wall
    return (datetime.fromisoformat(wall) + timedelta(seconds=seconds)).isoformat()


def _split_line(
    line: TranscriptLine,
    samples: np.ndarray,
    cuts: Sequence[int],
    decode: Callable[[np.ndarray], str],
    should_cancel: Callable[[], bool],
) -> list[TranscriptLine] | None:
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
        parts.append(
            replace(
                line,
                start=line.start + first / SAMPLE_RATE,
                end=line.end if last == samples.size else line.start + last / SAMPLE_RATE,
                wall=_shifted_wall(line.wall, first / SAMPLE_RATE),
                text=text,
            )
        )
    return parts


def group_and_split(
    lines: Sequence[TranscriptLine],
    embeddings: Sequence[np.ndarray],
    *,
    read_source: Callable[[], np.ndarray | None] | None,
    speaker_model: Path,
    embed: Callable[[np.ndarray], np.ndarray],
    decode: Callable[[np.ndarray], str],
    progress: Callable[[float], None] = lambda _fraction: None,
    should_cancel: Callable[[], bool] = lambda: False,
    speaker_count: int | None = None,
    label_prefix: str = "Speaker",
) -> GroupedLines | None:
    """Give the lines of one source their speakers from pieces of its saved audio.

    Group the pieces into speakers. Each line gets the speaker with the most overlap, or the
    closest voice if no piece overlaps it. A line where another voice holds a run of at least
    1 s splits, and each part gets the speaker of its run.

    *read_source* returns all samples of the source, or ``None`` on a cancel. A *read_source*
    of ``None`` means the source has no saved audio. A source with no audio or no speech groups
    whole lines. *progress* gets a fraction that never falls. Return ``None`` on a cancel.
    """
    original = tuple(lines)
    vectors = tuple(embeddings)
    if not original:
        progress(1.0)
        return GroupedLines((), ())

    def stage(start: float, end: float) -> Callable[[int, int], None]:
        # The grouping count can pass its total near the end of a pass.
        return lambda done, total: progress(start + (end - start) * min(done, total) / total)

    def whole_lines(first_progress: float) -> GroupedLines | None:
        grouped = relabel_system_lines(
            original,
            vectors,
            progress=stage(first_progress, 1.0),
            should_cancel=should_cancel,
            speaker_count=speaker_count,
            label_prefix=label_prefix,
        )
        return None if grouped is None else GroupedLines(grouped, tuple(range(len(grouped))))

    if read_source is None:
        return whole_lines(0.0)
    samples = read_source()
    if samples is None:
        return None
    pieces = find_speech_pieces(
        samples,
        speaker_model,
        progress=lambda fraction: progress(_FOUND_SHARE * fraction),
        should_cancel=should_cancel,
    )
    if pieces is None:
        return None
    if not pieces:
        # The pass has reported progress up to this share.
        return whole_lines(_FOUND_SHARE)

    id_prefix = label_prefix.lower()
    piece_lines = tuple(
        TranscriptLine(
            start=start,
            end=end,
            wall="",
            source=original[0].source,
            speaker_id=f"{id_prefix}-1",
            label=f"{label_prefix} 1",
            text="",
        )
        for start, end in pieces
    )
    piece_vectors = []
    for done, (start, end) in enumerate(pieces, 1):
        if should_cancel():
            return None
        piece_vectors.append(embed(samples[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]))
        progress(_FOUND_SHARE + (_EMBEDDED_SHARE - _FOUND_SHARE) * done / len(pieces))
    grouped_pieces = relabel_system_lines(
        piece_lines,
        piece_vectors,
        threshold=_GROUPING_THRESHOLD,
        progress=stage(_EMBEDDED_SHARE, _GROUPED_SHARE),
        should_cancel=should_cancel,
        speaker_count=speaker_count,
        label_prefix=label_prefix,
    )
    if grouped_pieces is None:
        return None

    voices = average_voices(grouped_pieces, piece_vectors)
    new_lines: list[TranscriptLine] = []
    parents: list[int] = []
    # Speakers in order of their first line, each with the indices of its new lines.
    members: dict[str, list[int]] = {}
    split_count = 0
    for index, (line, vector) in enumerate(zip(original, vectors, strict=True)):
        shares, runs = _line_speech(line, grouped_pieces)
        parts = None
        if len(runs) > 1:
            parts = _split_line(
                line,
                samples[int(line.start * SAMPLE_RATE) : int(line.end * SAMPLE_RATE)],
                _cuts(line, runs),
                decode,
                should_cancel,
            )
            if parts is None:
                return None
        if parts:
            split_count += 1
            speakers = [run[0] for run in runs]
        else:
            parts = [line]
            speakers = [
                max(shares, key=shares.__getitem__) if shares else _closest_voice(vector, voices)
            ]
        for part, speaker_id in zip(parts, speakers, strict=True):
            members.setdefault(speaker_id, []).append(len(new_lines))
            new_lines.append(part)
            parents.append(index)
        progress(_GROUPED_SHARE + (1.0 - _GROUPED_SHARE) * (index + 1) / len(original))

    labeled = apply_cluster_labels(
        tuple(new_lines),
        list(members.values()),
        np.array([line.end - line.start for line in new_lines]),
        label_prefix,
    )
    log.debug(
        fmt_event(
            "live",
            "speakers_from_pieces",
            piece_count=len(pieces),
            phrase_count=split_count,
            line_count=len(labeled),
        )
    )
    return GroupedLines(labeled, tuple(parents))
