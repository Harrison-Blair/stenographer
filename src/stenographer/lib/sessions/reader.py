# SPDX-License-Identifier: GPL-3.0-or-later
"""Read session folders, transcript rows, audio metrics, and activity."""

from __future__ import annotations

import json
import math
import re
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions.models import SessionDetail, SessionSummary

_SESSION_ID = re.compile(r"(?P<start>\d{8}T\d{6}Z)(?:-\d+)?\Z")
_REVISION = re.compile(r"transcript\.r(?P<number>[2-9]|[1-9]\d+)\.jsonl\Z")
_SOURCE_FILE = re.compile(r"source\.[A-Za-z0-9]{1,8}\Z")
_ACTIVITY_BINS = 64
_AUDIO_SOURCES = ("mic", "system")


def session_started_at(session_id: str) -> datetime | None:
    match = _SESSION_ID.fullmatch(session_id)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("start"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def session_directory(root: Path, session_id: str) -> Path | None:
    if session_started_at(session_id) is None:
        return None
    candidate = root / session_id
    try:
        mode = candidate.lstat().st_mode
    except OSError:
        return None
    if not stat.S_ISDIR(mode):
        return None
    return candidate


def list_session_ids(root: Path) -> list[str]:
    try:
        entries = tuple(root.iterdir())
    except FileNotFoundError:
        return []
    except OSError:
        return []
    ids = [
        entry.name
        for entry in entries
        if session_started_at(entry.name) is not None and session_directory(root, entry.name)
    ]
    return sorted(ids, key=lambda value: (session_started_at(value), value), reverse=True)


def session_metadata(directory: Path) -> dict:
    """Return the session.json object, or an empty one when it is absent or unreadable."""
    metadata_path = directory / "session.json"
    try:
        if not stat.S_ISREG(metadata_path.lstat().st_mode):
            return {}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def source_file_path(directory: Path, metadata: dict) -> Path | None:
    """Return the copied source of a file session, or None when the field is invalid."""
    name = metadata.get("source_file")
    if not isinstance(name, str) or _SOURCE_FILE.fullmatch(name) is None:
        return None
    candidate = directory / name
    try:
        if not stat.S_ISREG(candidate.lstat().st_mode):
            return None
    except OSError:
        return None
    return candidate


def _label_state(revision: str, metadata: dict) -> str:
    if revision == "transcript.jsonl":
        return "live"
    method = metadata.get("method")
    if method == "diarization":
        return "relabeled"
    return method if isinstance(method, str) and method else "revised"


def current_revision(directory: Path) -> tuple[str, Path, bool]:
    metadata_path = directory / "session.json"
    try:
        if not stat.S_ISREG(metadata_path.lstat().st_mode):
            return "transcript.jsonl", directory / "transcript.jsonl", True
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "transcript.jsonl", directory / "transcript.jsonl", False
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "transcript.jsonl", directory / "transcript.jsonl", True
    revision = metadata.get("current_revision") if isinstance(metadata, dict) else None
    if revision == "transcript.jsonl":
        return revision, directory / revision, False
    if isinstance(revision, str) and _REVISION.fullmatch(revision):
        return revision, directory / revision, False
    return "transcript.jsonl", directory / "transcript.jsonl", True


def read_transcript(path: Path) -> tuple[tuple[TranscriptLine, ...], bool]:
    lines: list[TranscriptLine] = []
    renames: dict[str, str] = {}
    interrupted = False
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return (), True
        stream = path.open(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return (), True
    except OSError:
        return (), True

    with stream:
        for raw in stream:
            if not raw.endswith("\n"):
                interrupted = True
            try:
                record = json.loads(raw)
                if not isinstance(record, dict):
                    raise ValueError("record is not an object")
                if record.get("type") == "rename":
                    labels = record.get("labels")
                    if not isinstance(labels, dict) or any(
                        not isinstance(key, str) or not isinstance(value, str)
                        for key, value in labels.items()
                    ):
                        raise ValueError("invalid rename record")
                    renames.update(labels)
                    continue
                if "type" in record:
                    raise ValueError("unknown transcript record type")
                start = record["start"]
                end = record["end"]
                if (
                    isinstance(start, bool)
                    or not isinstance(start, (int, float))
                    or isinstance(end, bool)
                    or not isinstance(end, (int, float))
                    or not math.isfinite(start)
                    or not math.isfinite(end)
                    or start < 0
                    or end < start
                ):
                    raise ValueError("invalid phrase interval")
                required_strings = ("wall", "source", "speaker_id", "label", "text")
                if any(not isinstance(record.get(key), str) for key in required_strings):
                    raise ValueError("invalid transcript fields")
                lines.append(
                    TranscriptLine(
                        start=float(start),
                        end=float(end),
                        wall=record["wall"],
                        source=record["source"],
                        speaker_id=record["speaker_id"],
                        label=record["label"],
                        text=record["text"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                interrupted = True

    return tuple(
        sorted(
            (replace(line, label=renames.get(line.speaker_id, line.label)) for line in lines),
            key=lambda line: (line.start, line.end),
        )
    ), interrupted


def _audio_info(path: Path) -> tuple[int, int] | None:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        info = sf.info(path)
    except (OSError, RuntimeError, ValueError):
        return None
    if info.samplerate <= 0 or info.frames < 0:
        return None
    return info.frames, info.samplerate


def _activity(path: Path) -> tuple[float, ...]:
    info = _audio_info(path)
    if info is None:
        return ()
    frames, _ = info
    if frames == 0:
        return ()
    boundaries = np.linspace(0, frames, _ACTIVITY_BINS + 1, dtype=np.int64)
    levels: list[float] = []
    try:
        with sf.SoundFile(path) as audio:
            for index in range(_ACTIVITY_BINS):
                start, end = int(boundaries[index]), int(boundaries[index + 1])
                if end == start:
                    continue
                audio.seek(start)
                samples = audio.read(end - start, dtype="float32", always_2d=True)
                if len(samples) != end - start:
                    return ()
                levels.append(float(np.sqrt(np.mean(np.square(samples), dtype=np.float64))))
    except (OSError, RuntimeError, ValueError):
        return ()
    return tuple(levels)


def read_session(directory: Path, session_id: str, *, with_activity: bool) -> SessionDetail:
    started_at = session_started_at(session_id)
    if started_at is None:
        raise ValueError("invalid session ID")
    revision, transcript_path, interrupted = current_revision(directory)
    lines, transcript_partial = read_transcript(transcript_path)
    interrupted |= transcript_partial

    current_markdown = transcript_path.with_suffix(".md")
    try:
        if not stat.S_ISREG(current_markdown.lstat().st_mode):
            interrupted = True
    except OSError:
        interrupted = True

    original = directory / "transcript.jsonl"
    labels_revised = False
    if revision != "transcript.jsonl":
        original_lines, _ = read_transcript(original)
        original_labels = {line.speaker_id: line.label for line in original_lines}
        current_labels = {line.speaker_id: line.label for line in lines}
        labels_revised = current_labels != original_labels
    try:
        if not stat.S_ISREG(original.lstat().st_mode):
            interrupted = True
    except OSError:
        interrupted = True

    for candidate in directory.iterdir():
        if candidate.name.startswith("transcript.r") and candidate.suffix in {".jsonl", ".md"}:
            match = re.fullmatch(r"transcript\.r(\d+)\.(jsonl|md)", candidate.name)
            if match is not None:
                pair = directory / f"transcript.r{match.group(1)}"
                if not (pair.with_suffix(".jsonl").is_file() and pair.with_suffix(".md").is_file()):
                    interrupted = True

    metadata = session_metadata(directory)
    kind = "file" if metadata.get("kind") == "file" else "rec"
    source_ids = {line.source for line in lines}
    audio_sizes = 0
    durations: list[float] = []
    activity: dict[str, tuple[float, ...]] = {}
    if kind == "file":
        source = source_file_path(directory, metadata)
        if source is None:
            interrupted = True
        else:
            try:
                audio_sizes = source.lstat().st_size
            except OSError:
                interrupted = True
        probe_duration = metadata.get("duration_seconds")
        if (
            isinstance(probe_duration, (int, float))
            and not isinstance(probe_duration, bool)
            and math.isfinite(probe_duration)
            and probe_duration >= 0
        ):
            durations.append(float(probe_duration))
    for source in _AUDIO_SOURCES if kind == "rec" else ():
        audio_path = directory / f"{source}.flac"
        audio_info = _audio_info(audio_path)
        if audio_info is None:
            try:
                exists = audio_path.lstat()
            except OSError:
                exists = None
            if source in source_ids or exists is not None:
                interrupted = True
            if with_activity:
                activity[source] = ()
            continue
        frames, sample_rate = audio_info
        durations.append(frames / sample_rate)
        try:
            audio_sizes += audio_path.stat().st_size
        except OSError:
            interrupted = True
        if with_activity:
            activity[source] = _activity(audio_path)
            if frames and not activity[source]:
                interrupted = True

    duration = max([*durations, *(line.end for line in lines)], default=0.0)
    if with_activity:
        for source in _AUDIO_SOURCES:
            activity.setdefault(source, ())

    talk_time: dict[str, float] = {}
    for line in lines:
        talk_time[line.label] = talk_time.get(line.label, 0.0) + line.end - line.start
    summary = SessionSummary(
        session_id=session_id,
        started_at=started_at,
        duration_seconds=duration,
        speaker_count=len({line.speaker_id for line in lines}),
        audio_size_bytes=audio_sizes,
        interrupted=interrupted,
        kind=kind,
        source_name=(
            metadata["source_name"]
            if kind == "file" and isinstance(metadata.get("source_name"), str)
            else None
        ),
        label_state=_label_state(revision, metadata),
    )
    return SessionDetail(
        summary,
        lines,
        talk_time,
        activity,
        revision,
        labels_revised,
        diarize_mic=metadata.get("diarize_mic") is True,
    )
