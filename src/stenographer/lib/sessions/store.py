# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and manage saved live sessions."""

from __future__ import annotations

from pathlib import Path

from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.models import SessionDetail, SessionSummary
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
