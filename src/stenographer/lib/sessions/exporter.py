# SPDX-License-Identifier: GPL-3.0-or-later
"""Render and export transcript lines in shared output formats."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions.persistence import atomic_write_private

SUPPORTED_FORMATS = frozenset({"md", "jsonl", "srt", "txt"})
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds:03d}"


def render_transcript(lines: Iterable[TranscriptLine], format: str) -> str:
    """Render transcript lines as Markdown, JSONL, SRT, or plain text."""
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported transcript format: {format}")
    rows = tuple(lines)
    if format == "jsonl":
        return "".join(json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in rows)
    if format == "srt":
        cues = []
        for index, line in enumerate(rows, start=1):
            text = " ".join(line.text.splitlines())
            cues.append(
                f"{index}\n{_srt_timestamp(line.start)} --> {_srt_timestamp(line.end)}\n"
                f"{line.label}: {text}"
            )
        return "\n\n".join(cues) + ("\n" if cues else "")
    if format == "md":
        output = ["# Transcript", ""]
        output.extend(f"[{_timestamp(line.start)}] **{line.label}:** {line.text}" for line in rows)
        return "\n".join(output) + "\n"
    return "".join(
        f"[{_timestamp(line.start)}] {line.label}: {' '.join(line.text.splitlines())}\n"
        for line in rows
    )


def export_transcript(
    lines: Iterable[TranscriptLine],
    output_folder: str | Path,
    format: str,
    *,
    filename: str = "transcript",
) -> Path:
    """Write one private transcript file in the caller's output folder."""
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported transcript format: {format}")
    if _FILENAME.fullmatch(filename) is None:
        raise ValueError("filename must be one safe path component")
    output = Path(output_folder).expanduser()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = output / f"{filename}.{format}"
    atomic_write_private(path, render_transcript(lines, format).encode("utf-8"))
    return path
