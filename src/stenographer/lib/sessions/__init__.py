# SPDX-License-Identifier: GPL-3.0-or-later
"""Session storage package.

- ``models.py`` defines session summaries and loaded session data.
- ``reader.py`` parses session files and derives transcript and audio metrics.
- ``store.py`` exposes safe session operations and an in-memory title and
  transcript search.
- ``exporter.py`` renders transcripts for session and file exports.
- ``persistence.py`` writes private session files atomically.
- ``errors.py`` defines session storage errors.
"""

from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.exporter import export_transcript
from stenographer.lib.sessions.models import SessionDetail, SessionSummary
from stenographer.lib.sessions.store import SessionStore

__all__ = [
    "SessionDetail",
    "SessionNotFoundError",
    "SessionStore",
    "SessionSummary",
    "export_transcript",
]
