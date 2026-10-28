# SPDX-License-Identifier: GPL-3.0-or-later
"""One row of the Library list: a saved session, a file job, or a session with a job."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stenographer.lib.sessions.models import SessionSummary

ACTIVE_JOB_STATES = frozenset({"queued", "running"})


@dataclass(frozen=True)
class LibraryEntry:
    """A session row (``summary``), a job row (``summary`` is None), or a session row with
    the revision job that writes into it (``job``)."""

    entry_id: str
    summary: SessionSummary | None
    job: Any = None
    job_name: str = ""
    listed_at: datetime | None = None

    @property
    def session_id(self) -> str | None:
        return None if self.summary is None else self.summary.session_id

    @property
    def kind(self) -> str:
        return "file" if self.summary is None else self.summary.kind

    @property
    def job_active(self) -> bool:
        return self.job is not None and self.job.state in ACTIVE_JOB_STATES
