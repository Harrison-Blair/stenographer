# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and manage saved live sessions."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.sessions.errors import (
    SessionNotFoundError,
    SessionSourceError,
    SessionWriteCancelledError,
    StaleRevisionError,
)
from stenographer.lib.sessions.exporter import export_transcript, render_transcript
from stenographer.lib.sessions.models import SessionDetail, SessionSummary
from stenographer.lib.sessions.persistence import atomic_write_private, write_private_temporary
from stenographer.lib.sessions.reader import (
    current_revision,
    list_session_ids,
    read_session,
    read_transcript,
    session_directory,
    session_metadata,
    session_started_at,
    source_file_path,
)
from stenographer.lib.sessions.session_locks import SessionLocks

_SOURCE_SUFFIX = re.compile(r"[A-Za-z0-9]{1,8}\Z")
_RECORDED_SOURCES = ("mic.flac", "system.flac")


class SessionStore:
    """Access session folders below an explicit sessions root."""

    def __init__(self, sessions_root: str | Path) -> None:
        self.root = Path(sessions_root).expanduser().resolve(strict=False)
        self._search_texts: dict[str, tuple[tuple[str, int], tuple[str, ...]]] = {}

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        """Return session summaries, newest first."""
        summaries = []
        for session_id in list_session_ids(self.root):
            directory = session_directory(self.root, session_id)
            if directory is not None:
                summaries.append(read_session(directory, session_id, with_activity=False).summary)
        return tuple(summaries)

    def search(self, query: str) -> tuple[str, ...]:
        """Return the IDs of sessions whose title or current transcript holds the query.

        The match ignores case, and the IDs come newest first. A blank query matches every
        session. The text of each current revision stays only in memory, keyed by session ID,
        revision file, and its ``mtime_ns``. An unreadable session is skipped.
        """
        session_ids = list_session_ids(self.root)
        for gone in self._search_texts.keys() - set(session_ids):
            del self._search_texts[gone]
        if not query.strip():
            return tuple(session_ids)
        needle = query.casefold()
        return tuple(
            session_id
            for session_id in session_ids
            if any(needle in text for text in self._searchable_texts(session_id))
        )

    def read(self, session_id: str) -> SessionDetail:
        """Read the transcript and derive talk time and FLAC activity on demand."""
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
        expected_revision: str,
        revision_name: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Save replacement lines as a new current revision when the read revision is current.

        The JSONL and Markdown files go to private temporary names first, then to their
        final names, and ``session.json`` is replaced last. An error or a cancel at any
        step removes each file that this call made.
        """
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        if not isinstance(method, str) or not method.strip():
            raise ValueError("revision method must not be empty")
        revised = tuple(lines)
        if any(not isinstance(line, TranscriptLine) for line in revised):
            raise TypeError("revision lines must be TranscriptLine values")
        with SessionLocks.lock(self.root, session_id):
            original = directory / "transcript.jsonl"
            if not original.is_file():
                raise FileNotFoundError(f"original transcript is missing: {original}")
            current, _, _ = current_revision(directory)
            if current != expected_revision:
                raise StaleRevisionError(
                    f"session {session_id} changed since it was read: "
                    f"expected {expected_revision}, found {current}"
                )
            filename = self._next_revision_name(directory)
            if revision_name is not None and revision_name != filename:
                raise StaleRevisionError(
                    f"session {session_id} changed since it was read: "
                    f"expected next revision {revision_name}, found {filename}"
                )
            markdown_name = filename.removesuffix(".jsonl") + ".md"
            directory.chmod(0o700)
            jsonl = "".join(
                json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in revised
            ).encode("utf-8")
            markdown = render_transcript(revised, "md").encode("utf-8")
            metadata = {
                **session_metadata(directory),
                "current_revision": filename,
                "method": method.strip(),
            }
            made: list[Path] = []
            try:
                made.append(write_private_temporary(directory, filename, jsonl))
                self._check_cancel(should_cancel)
                made.append(write_private_temporary(directory, markdown_name, markdown))
                self._check_cancel(should_cancel)
                os.replace(made[0], directory / filename)
                made[0] = directory / filename
                self._check_cancel(should_cancel)
                os.replace(made[1], directory / markdown_name)
                made[1] = directory / markdown_name
                self._check_cancel(should_cancel)
                atomic_write_private(directory / "session.json", self._metadata_bytes(metadata))
            except BaseException:
                for path in made:
                    with contextlib.suppress(OSError):
                        path.unlink(missing_ok=True)
                raise
        return filename

    def next_revision_name(self, session_id: str) -> str:
        """Return the file name that the next revision of this session gets."""
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        with SessionLocks.lock(self.root, session_id):
            return self._next_revision_name(directory)

    def create_file_session(
        self,
        source: str | Path,
        *,
        started_at: datetime,
        duration_seconds: float,
        lines: Iterable[TranscriptLine],
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Make a file session folder with a private copy of the source and its transcript.

        An error or a cancel removes the folder that this call made.
        """
        source = Path(source).expanduser()
        rows = tuple(lines)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        started_at = started_at.astimezone(UTC)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        while True:
            session_id = started_at.strftime("%Y%m%dT%H%M%SZ")
            directory = self.root / session_id
            try:
                directory.mkdir(mode=0o700)
                break
            except FileExistsError:
                started_at += timedelta(seconds=1)
        try:
            with SessionLocks.lock(self.root, session_id):
                directory.chmod(0o700)
                suffix = source.suffix[1:]
                extension = suffix.lower() if _SOURCE_SUFFIX.fullmatch(suffix) else "bin"
                source_file = f"source.{extension}"
                fd = os.open(directory / source_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, output)
                    output.flush()
                    os.fsync(output.fileno())
                (directory / source_file).chmod(0o600)
                self._check_cancel(should_cancel)
                atomic_write_private(
                    directory / "transcript.jsonl",
                    "".join(
                        json.dumps(asdict(line), ensure_ascii=False) + "\n" for line in rows
                    ).encode("utf-8"),
                )
                self._check_cancel(should_cancel)
                atomic_write_private(
                    directory / "transcript.md", render_transcript(rows, "md").encode("utf-8")
                )
                self._check_cancel(should_cancel)
                metadata = {
                    "current_revision": "transcript.jsonl",
                    "duration_seconds": float(duration_seconds),
                    "kind": "file",
                    "source_file": source_file,
                    "source_name": source.name,
                }
                atomic_write_private(directory / "session.json", self._metadata_bytes(metadata))
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return session_id

    def source_audio(self, session_id: str) -> Path:
        """Return the validated copied source audio of a file session."""
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        metadata = session_metadata(directory)
        if metadata.get("kind") != "file":
            raise SessionSourceError(f"session is not a file session: {session_id}")
        source = source_file_path(directory, metadata)
        if source is None:
            raise SessionSourceError(f"source audio is missing or invalid: {session_id}")
        return source

    def revision_target(self, path: str | Path) -> tuple[str, str] | None:
        """Return the session and source that a file job revises, or None for a new session.

        The source is ``mic`` or ``system`` for a recorded source directly in a session
        folder, or ``file`` for the copied source of a file session.
        """
        try:
            resolved = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        directory = resolved.parent
        if directory.parent != self.root:
            return None
        session_id = directory.name
        if session_directory(self.root, session_id) is None:
            return None
        if resolved.name in _RECORDED_SOURCES:
            return session_id, resolved.name.removesuffix(".flac")
        metadata = session_metadata(directory)
        if metadata.get("kind") == "file" and source_file_path(directory, metadata) == resolved:
            return session_id, "file"
        return None

    def export(self, session_id: str, output_folder: str | Path, format: str) -> Path:
        """Export the current transcript to the requested output folder."""
        detail = self.read(session_id)
        return export_transcript(
            detail.lines,
            output_folder,
            format,
            filename=session_id,
        )

    def delete(self, session_id: str) -> None:
        """Delete one explicitly named session folder below the sessions root."""
        directory = session_directory(self.root, session_id)
        if directory is None:
            raise SessionNotFoundError(f"session not found: {session_id}")
        with SessionLocks.lock(self.root, session_id):
            shutil.rmtree(directory)

    def rename_speaker(self, session_id: str, speaker_id: str, name: str) -> str:
        """Save a new revision with the selected speaker's display name changed."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("speaker name must not be empty")
        with SessionLocks.lock(self.root, session_id):
            detail = self.read(session_id)
            if not any(line.speaker_id == speaker_id for line in detail.lines):
                raise ValueError(f"speaker not found: {speaker_id}")
            renamed = tuple(
                replace(line, label=cleaned_name) if line.speaker_id == speaker_id else line
                for line in detail.lines
            )
            return self.write_revision(
                session_id, renamed, method="rename", expected_revision=detail.revision
            )

    def _searchable_texts(self, session_id: str) -> tuple[str, ...]:
        directory = session_directory(self.root, session_id)
        if directory is None:
            return ()
        try:
            revision, path, _ = current_revision(directory)
            key = (revision, path.lstat().st_mtime_ns)
            path.open("rb").close()
        except OSError:
            self._search_texts.pop(session_id, None)
            return ()
        cached = self._search_texts.get(session_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        metadata = session_metadata(directory)
        if metadata.get("kind") == "file":
            name = metadata.get("source_name")
            titles = (name,) if isinstance(name, str) else ()
        else:
            titles = (session_id, session_started_at(session_id).strftime("%Y-%m-%d %H:%M"))
        lines, _ = read_transcript(path)
        texts = tuple(text.casefold() for text in (*titles, *(line.text for line in lines)))
        self._search_texts[session_id] = (key, texts)
        return texts

    @staticmethod
    def _next_revision_name(directory: Path) -> str:
        number = 2
        while any(
            (directory / f"transcript.r{number}.{suffix}").exists() for suffix in ("jsonl", "md")
        ):
            number += 1
        return f"transcript.r{number}.jsonl"

    @staticmethod
    def _metadata_bytes(metadata: dict) -> bytes:
        return (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

    @staticmethod
    def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel is not None and should_cancel():
            raise SessionWriteCancelledError("session write was cancelled")
