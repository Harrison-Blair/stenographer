# SPDX-License-Identifier: GPL-3.0-or-later
"""Own long-lived work shared by hub sections."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.logging.pipeline import fmt_event
from stenographer.lib.sessions import SessionStore
from stenographer.lib.sessions.jobs import SessionJobs

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    import numpy as np

    from stenographer.lib.config.models import Config
    from stenographer.lib.files.engine import FilesEngine
    from stenographer.lib.platform.platform import Platform


class HubServices:
    """Keep recording and Files work independent of the selected section."""

    def __init__(
        self,
        config: Config,
        platform: Platform,
        *,
        session_factory: Callable[..., LiveSession] = LiveSession,
        session_store: SessionStore | None = None,
        player_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        files_engine_factory: Callable[..., FilesEngine] | None = None,
        device_query: Callable[[], list[tuple[str, str]]] | None = None,
        media_decoder: Callable[[Path], Generator[np.ndarray]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._platform = platform
        self._session_factory = session_factory
        self._session_store = session_store
        self._session_jobs: SessionJobs | None = None
        self._player_factory = player_factory
        self._player: subprocess.Popen | None = None
        self._player_session_id: str | None = None
        self._player_temp_path: Path | None = None
        self._player_started_at = 0.0
        self._clock = clock
        self._player_lock = threading.Lock()
        self._stopped_players: set[subprocess.Popen] = set()
        self._session: LiveSession | None = None
        self._files_engine_factory = files_engine_factory
        self._files_engine = None
        self._files_lock = threading.Lock()
        self._files_closed = False
        self.files_job = None
        self._device_query = device_query
        self._media_decoder = media_decoder
        self._stopping: list[LiveSession] = []
        self._stops_changed = threading.Condition()
        self.last_saved: LiveSession | None = None
        # Each failed stop and its error since the last recording start; Record shows the last one.
        self.failed_stops: list[tuple[LiveSession, str]] = []
        self.next_sources = {"mic": True, "system": True}
        self.next_device: str | None = None
        self.next_device_label: str | None = None

    @property
    def recording(self) -> bool:
        return self._session is not None

    @property
    def active_session_id(self) -> str | None:
        return None if self._session is None else self._session.path.name

    @property
    def session(self) -> LiveSession | None:
        return self._session

    def update_config(self, config: Config) -> None:
        """Use saved settings for new work without changing an active session."""

        self._config = config
        if self._session_jobs is not None:
            self._session_jobs.update_config(config)

    @property
    def session_store(self) -> SessionStore:
        if self._session_store is None:
            data_dir = self._platform.data_dir(os.environ, Path.home())
            self._session_store = SessionStore(data_dir / "sessions")
        return self._session_store

    @property
    def session_jobs(self) -> SessionJobs:
        if self._session_jobs is None:
            self._session_jobs = SessionJobs(
                self.session_store,
                self._config,
                self._platform,
                media_decoder=self._media_decoder,
            )
        return self._session_jobs

    @property
    def files_running(self) -> bool:
        return any(
            getattr(job, "state", "queued") in {"queued", "running"} for job in self.files_jobs
        )

    @property
    def files_jobs(self) -> tuple[object, ...]:
        if self._files_engine is not None:
            return tuple(self._files_engine.jobs)
        return () if self.files_job is None else (self.files_job,)

    @property
    def files_engine(self) -> FilesEngine | None:
        """Return the files engine once a file is submitted and until it closes."""
        return self._files_engine

    def submit_file(self, path: str | Path, **options):
        with self._files_lock:
            if self._files_closed:
                raise RuntimeError("Files service is closed")
            if self._files_engine is None:
                factory = self._files_engine_factory
                if factory is None:
                    from stenographer.lib.files.engine import FilesEngine

                    factory = FilesEngine
                self._files_engine = factory(self._config, platform=self._platform)
            self.files_job = self._files_engine.submit(path, **options)
            return self.files_job

    def cancel_file(self, job) -> bool:
        return job.cancel()

    def close_files(self) -> None:
        with self._files_lock:
            engine = self._files_engine
            self._files_engine = None
            self.files_job = None
            self._files_closed = True
        if engine is not None:
            engine.close()

    def warm_worker(self) -> None:
        """Start and close one child before Textual captures stderr."""
        process = self._platform.asr_transport().spawn(on_log=lambda _record: None)
        process.close()

    def start_recording(self) -> None:
        if self._session is not None:
            return
        session = self._session_factory(
            self._config,
            diarize_mic=self._config.live.diarize_mic,
            platform=self._platform,
            mic=self.next_sources["mic"],
            system=self.next_sources["system"],
            device=self.next_device,
        )
        self._session = session
        try:
            session.start()
        except Exception:
            self._session = None
            session.stop()
            raise
        with self._stops_changed:
            self.failed_stops = []

    def stop_recording(self) -> None:
        session = self.begin_stop()
        if session is not None:
            self.finish_stop(session)

    @property
    def stopping_sessions(self) -> tuple[LiveSession, ...]:
        """Return the sessions whose stop runs, in stop order."""
        with self._stops_changed:
            return tuple(self._stopping)

    def begin_stop(self) -> LiveSession | None:
        """End the recording at once; the caller runs ``finish_stop`` in the background."""
        with self._stops_changed:
            session = self._session
            if session is None:
                return None
            self._session = None
            self._stopping.append(session)
            self.last_saved = session
        return session

    def finish_stop(self, session: LiveSession) -> None:
        """Save the session; it leaves the stopping list at the end."""
        try:
            session.stop()
        except Exception as exc:
            with self._stops_changed:
                self.failed_stops.append((session, str(exc)))
            raise
        finally:
            with self._stops_changed:
                self._stopping.remove(session)
                self._stops_changed.notify_all()

    def show_next_failed_stop(self) -> None:
        """Bring the next failed stop forward on Record."""
        with self._stops_changed:
            self.failed_stops.insert(0, self.failed_stops.pop())

    def wait_for_stops(self, timeout: float | None = None) -> bool:
        """Wait until no stop runs; return false when the timeout ends first."""
        with self._stops_changed:
            return self._stops_changed.wait_for(lambda: not self._stopping, timeout)

    def toggle_next_source(self, source: str) -> None:
        """Turn a source of the next recording on or off."""
        self.next_sources[source] = not self.next_sources[source]

    def input_devices(self) -> list[tuple[str, str]]:
        """Return the input devices as ``(value, label)`` pairs; empty when none can record."""
        if self._device_query is not None:
            return self._device_query()
        from stenographer.lib.audio.probe import input_device_choices, query_devices

        return input_device_choices(query_devices())

    def choose_device(self, value: str | None, label: str | None) -> None:
        """Use a device for the next recordings of this run; ``None`` uses the saved setting."""
        self.next_device = value
        self.next_device_label = label

    def toggle_session_playback(
        self, session_id: str, on_failure: Callable[[int], None] | None = None
    ) -> None:
        """Stop this session's player, or play it in place of any other session.

        ``on_failure`` gets the status of a player that exits with an error by
        itself; it runs on the player's watcher thread.
        """
        with self._player_lock:
            same_session = self._player_session_id == session_id
            if self._stop_player_locked() and same_session:
                return
            if self._player_temp_path is not None:
                self._player_temp_path.unlink(missing_ok=True)
                self._player_temp_path = None
            mixed_path = self.session_jobs.write_play_audio(session_id)
            try:
                process = self._player_factory(["pw-play", str(mixed_path)])
            except Exception:
                mixed_path.unlink(missing_ok=True)
                raise
            self._player = process
            self._player_session_id = session_id
            self._player_temp_path = mixed_path
            self._player_started_at = self._clock()
            log.info(
                fmt_event("hub", "session_playback_started", session_id=session_id, pid=process.pid)
            )
            threading.Thread(
                target=self._watch_player,
                args=(process, mixed_path, session_id, on_failure),
                name="stenographer-session-player",
                daemon=True,
            ).start()

    def session_playback(self) -> tuple[str, float] | None:
        """Return the session that plays and the seconds since its player started, or ``None``."""
        with self._player_lock:
            if self._player is None or self._player_session_id is None:
                return None
            return self._player_session_id, self._clock() - self._player_started_at

    def stop_session_playback(self) -> None:
        with self._player_lock:
            self._stop_player_locked()

    def _stop_player_locked(self) -> bool:
        """Terminate a running player; return whether one ran."""
        process = self._player
        if process is None or process.poll() is not None:
            return False
        self._stopped_players.add(process)
        process.terminate()
        log.info(
            fmt_event(
                "hub",
                "session_playback_stopped",
                session_id=self._player_session_id,
                pid=process.pid,
            )
        )
        self._player = None
        self._player_session_id = None
        return True

    def _watch_player(
        self,
        process: subprocess.Popen,
        mixed_path: Path,
        session_id: str,
        on_failure: Callable[[int], None] | None,
    ) -> None:
        returncode = process.wait()
        log.info(
            fmt_event(
                "hub",
                "session_playback_finished",
                session_id=session_id,
                pid=process.pid,
                returncode=returncode,
            )
        )
        with self._player_lock:
            stopped = process in self._stopped_players
            self._stopped_players.discard(process)
            if self._player is process:
                self._player = None
                self._player_session_id = None
            if self._player_temp_path == mixed_path:
                self._player_temp_path = None
            mixed_path.unlink(missing_ok=True)
        if not stopped and returncode != 0 and on_failure is not None:
            on_failure(returncode)

    def cancel_files(self) -> None:
        engine = self._files_engine
        if engine is not None:
            self.close_files()
            return
        job = self.files_job
        if job is not None:
            job.cancel()
            self.files_job = None
