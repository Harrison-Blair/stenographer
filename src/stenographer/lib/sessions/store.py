# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and manage saved live sessions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, replace
from pathlib import Path

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.exporter import export_transcript, render_transcript
from stenographer.lib.sessions.models import SessionDetail, SessionSummary
from stenographer.lib.sessions.persistence import atomic_write_private
from stenographer.lib.sessions.reader import list_session_ids, read_session, session_directory


class SessionStore:
    """Access session folders below an explicit sessions root."""

    def __init__(self, sessions_root: str | Path) -> None:
        self.root = Path(sessions_root).expanduser().resolve(strict=False)

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        """Return session summaries, newest first."""
        summaries = []
        for session_id in list_session_ids(self.root):
            directory = session_directory(self.root, session_id)
            if directory is not None:
                summaries.append(read_session(directory, session_id, with_activity=False).summary)
        return tuple(summaries)

    def read(self, session_id: str) -> SessionDetail:
        """Read the current transcript and derive talk-time and activity data."""
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        return read_session(directory, session_id, with_activity=True)

    def write_revision(
        self,
        session_id: str,
        lines: Iterable[TranscriptLine],
        *,
        method: str,
    ) -> str:
        """Save replacement transcript lines as a new current revision."""
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        if not isinstance(method, str) or not method.strip():
            raise ValueError("revision method must not be empty")
        original = directory / "transcript.jsonl"
        if not original.is_file():
            raise FileNotFoundError(f"original transcript is missing: {original}")
        revised = tuple(lines)
        if any(not isinstance(line, TranscriptLine) for line in revised):
            raise TypeError("revision lines must be TranscriptLine values")

        revision_number = 2
        while any(
            (directory / f"transcript.r{revision_number}.{suffix}").exists()
            for suffix in ("jsonl", "md")
        ):
            revision_number += 1
        filename = f"transcript.r{revision_number}.jsonl"
        markdown_name = f"transcript.r{revision_number}.md"
        directory.chmod(0o700)
        jsonl = "".join(
            json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in revised
        ).encode("utf-8")
        markdown = render_transcript(revised, "md").encode("utf-8")
        atomic_write_private(directory / filename, jsonl)
        atomic_write_private(directory / markdown_name, markdown)
        metadata = {"current_revision": filename, "method": method.strip()}
        atomic_write_private(
            directory / "session.json",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        return filename

    def export(self, session_id: str, output_folder: str | Path, format: str) -> Path:
        """Export the current transcript to the requested output folder."""
        detail = self.read(session_id)
        return export_transcript(
            detail.lines,
            output_folder,
            format,
            filename=session_id,
        )

    def rename_speaker(self, session_id: str, speaker_id: str, name: str) -> str:
        """Save a new revision with the selected speaker's display name changed."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("speaker name must not be empty")
        detail = self.read(session_id)
        if not any(line.speaker_id == speaker_id for line in detail.lines):
            raise ValueError(f"speaker not found: {speaker_id}")
        renamed = tuple(
            replace(line, label=cleaned_name) if line.speaker_id == speaker_id else line
            for line in detail.lines
        )
        return self.write_revision(session_id, renamed, method="rename")
