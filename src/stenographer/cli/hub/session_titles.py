# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate session titles with the Refine model, off the event loop, one at a time."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.refine.client import installed_model_bytes
from stenographer.lib.refine.errors import RefineError
from stenographer.lib.refine.factory import keep_alive_for
from stenographer.lib.refine.title import request_title, transcript_samples
from stenographer.lib.sessions.errors import SessionNotFoundError
from stenographer.lib.sessions.reader import session_directory

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import Config
    from stenographer.lib.sessions import SessionStore

log = logging.getLogger(__name__)

NO_LINES = "This session has no transcript lines."
FAILED = "Could not generate a title"
THREAD_NAME = "stenographer-session-titles"


def model_installed(host: str, model: str) -> bool:
    return installed_model_bytes(host, model) is not None


@dataclass(frozen=True)
class _Request:
    session_id: str
    # True for ``g``; false for the automatic title of a saved recording or a file job.
    manual: bool
    # The ``user`` title that the user agreed to replace with ``g``.
    replace: str | None = None
    # The Refine host and model whose installed check let an automatic request start.
    checked: tuple[str, str] | None = None


class SessionTitles:
    """Ask for titles one at a time on a worker thread; the event loop reads ``generating``.

    The text of a title and of the transcript goes only to the Refine host and to
    ``session.json``. Log lines and notices name an outcome, never content.
    """

    def __init__(
        self,
        store: Callable[[], SessionStore],
        config: Callable[[], Config],
        *,
        request: Callable[..., str] = request_title,
        installed: Callable[[str, str], bool] = model_installed,
    ) -> None:
        self._store = store
        self._config = config
        self._request = request
        self._installed = installed
        # Guards the three fields below; never held across a request or a file read.
        self._lock = threading.Lock()
        self._queue: deque[_Request] = deque()
        # Replaced as a whole, so the event loop reads it without the lock.
        self._generating: frozenset[str] = frozenset()
        self._running = False
        # Replaced, never changed in place: the count of stored titles, read by the poll.
        self._stored = 0
        self._notices: deque[tuple[str, str]] = deque()

    @property
    def generating(self) -> frozenset[str]:
        """The sessions whose title the model works on, or that wait for ``g``."""
        return self._generating

    @property
    def stored(self) -> int:
        """How many titles this worker stored; a new value means a title to show."""
        return self._stored

    def take_notices(self) -> list[tuple[str, str]]:
        """Return and forget the ``(message, severity)`` notices of ``g``."""
        notices = []
        while self._notices:
            notices.append(self._notices.popleft())
        return notices

    def generate(self, session_id: str, *, replace: str | None = None) -> bool:
        """Queue ``g`` for a session; false when a title of it is already generating."""
        with self._lock:
            if session_id in self._generating:
                return False
            self._generating = self._generating | {session_id}
        self._put(_Request(session_id, manual=True, replace=replace))
        return True

    def generate_auto(self, session_id: str) -> None:
        """Queue the automatic title of a saved recording or a finished file job."""
        self._put(_Request(session_id, manual=False))

    def _put(self, item: _Request) -> None:
        """Queue one request; a worker thread runs while the queue has requests.

        The thread is a daemon: the hub exit does not wait for the model.
        """
        with self._lock:
            self._queue.append(item)
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run, name=THREAD_NAME, daemon=True).start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._running = False
                    return
                item = self._queue.popleft()
            if item.manual:
                try:
                    self._title(item)
                finally:
                    self._finish(item.session_id)
            else:
                self._run_auto(item.session_id)

    def _finish(self, session_id: str) -> None:
        with self._lock:
            self._generating = self._generating - {session_id}

    def _run_auto(self, session_id: str) -> None:
        refine = self._config().refine
        if not refine.enabled or not self._installed(refine.host, refine.model):
            log.debug(fmt_event("hub", "title_skipped", session_id=session_id, reason="refine"))
            return
        with self._lock:
            if session_id in self._generating:
                # ``g`` waits for this session; it gives the title.
                return
            self._generating = self._generating | {session_id}
        try:
            self._title(_Request(session_id, manual=False, checked=(refine.host, refine.model)))
        finally:
            self._finish(session_id)

    def _title(self, item: _Request) -> None:
        """Ask for one title and store it; a failure logs one warning and, for ``g``, a notice."""
        trigger = "key" if item.manual else "auto"
        started = time.perf_counter()
        try:
            saved = self._ask_and_store(item)
        except SessionNotFoundError:
            # The session was deleted: drop the result.
            return
        except Exception as exc:
            # A RefineError has a fixed reason; any other text could quote the reply.
            safe = isinstance(exc, RefineError)
            log_failure(log, logging.WARNING, "hub: title_failed", exc, safe=safe, trigger=trigger)
            # A session deleted during the request drops the result with no notice.
            if item.manual and session_directory(self._store().root, item.session_id) is not None:
                reason = f": {exc}" if safe else ""
                self._notices.append((f"{FAILED}{reason}.", "error"))
            return
        if saved is None:
            return
        if saved:
            self._stored += 1
        fields = {
            "session_id": item.session_id,
            "trigger": trigger,
            "ms": round((time.perf_counter() - started) * 1000),
        }
        if saved:
            log.info(fmt_event("hub", "title_saved", **fields))
        else:
            # The title changed during the request: the newer title stays.
            log.info(fmt_event("hub", "title_dropped", **fields))

    def _ask_and_store(self, item: _Request) -> bool | None:
        """Return whether the title was stored, or ``None`` when no request was made."""
        session_id = item.session_id
        store = self._store()
        detail = store.read(session_id)
        if not item.manual and detail.summary.title is not None:
            log.debug(fmt_event("hub", "title_skipped", session_id=session_id, reason="titled"))
            return None
        text = transcript_samples(
            tuple(f"{line.label}: {line.text}" for line in detail.lines if line.text.strip())
        )
        if not text:
            log.debug(fmt_event("hub", "title_skipped", session_id=session_id, reason="empty"))
            if item.manual:
                self._notices.append((NO_LINES, "warning"))
            return None
        config = self._config()
        refine = config.refine
        if not item.manual and (not refine.enabled or (refine.host, refine.model) != item.checked):
            # Refine changed after the installed check: that check no longer covers the request.
            log.debug(fmt_event("hub", "title_skipped", session_id=session_id, reason="refine"))
            return None
        title = self._request(
            config.refine.host,
            config.refine.model,
            text,
            keep_alive=keep_alive_for(config.asr.idle_unload_seconds),
        )
        replace = item.replace

        def allowed(current: str | None, source: str | None) -> bool:
            # An automatic title never replaces a title; ``g`` replaces a model title,
            # and a user title only when the user agreed to replace that title.
            if not item.manual:
                return current is None
            return current is None or source == "model" or current == replace

        return store.set_title(session_id, title, source="model", only_if=allowed)
