# SPDX-License-Identifier: GPL-3.0-or-later
"""Own long-lived work shared by hub sections."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from stenographer.cli.hub.session_jobs import SessionJobs
from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.live.models import LIVE_MODELS
from stenographer.lib.logging.pipeline import fmt_event
from stenographer.lib.sessions import SessionStore

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

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
    ) -> None:
        self._config = config
        self._platform = platform
        self._session_factory = session_factory
        self._session_store = session_store
        self._session_jobs: SessionJobs | None = None
        self._player_factory = player_factory
        self._player: subprocess.Popen | None = None
        self._player_pid: int | None = None
        self._player_session_id: str | None = None
        self._player_temp_path: Path | None = None
        self._player_lock = threading.Lock()
        self._session: LiveSession | None = None
        self._files_engine_factory = files_engine_factory
        self._files_engine = None
        self._files_lock = threading.Lock()
        self._files_closed = False
        self.files_job = None

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
            self._session_jobs = SessionJobs(self.session_store, self._config, self._platform)
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
    def files_output_folder(self) -> Path:
        return self._platform.data_dir(os.environ, Path.home()) / "files"

    @property
    def files_start_folder(self) -> Path:
        return self._platform.data_dir(os.environ, Path.home()) / "sessions"

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

    def open_files_result(self, output_path: str | Path) -> bool:
        result_folder = Path(output_path).expanduser().parent
        subprocess.Popen(
            ["xdg-open", str(result_folder)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(fmt_event("hub", "files_result_folder_opened"))
        return True

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
        process = self._platform.asr_transport().spawn(
            self._config.asr, on_log=lambda _record: None
        )
        process.close()

    def start_recording(self) -> None:
        if self._session is not None:
            return
        model_dir = self._platform.data_dir(os.environ, Path.home()) / "models" / "live"
        missing = [
            model.filename for model in LIVE_MODELS if not (model_dir / model.filename).is_file()
        ]
        if missing:
            raise RuntimeError(
                "live voice models are missing; run `stenographer model download --live` "
                f"(missing: {', '.join(missing)})"
            )
        session = self._session_factory(self._config, platform=self._platform)
        self._session = session
        try:
            session.start()
        except Exception:
            self._session = None
            session.stop()
            raise

    def stop_recording(self) -> None:
        session = self._session
        if session is None:
            return
        session.stop()
        self._session = None

    def rediarize_session(self, session_id: str) -> str:
        return self.session_jobs.rediarize(session_id)

    def retranscribe_session(self, session_id: str) -> str:
        return self.session_jobs.retranscribe(session_id)

    def toggle_session_playback(self, session_id: str) -> None:
        with self._player_lock:
            process = self._player
            if process is not None and process.poll() is None:
                if self._player_pid is None or process.pid != self._player_pid:
                    raise RuntimeError("session player process identity changed")
                process.terminate()
                log.info(
                    fmt_event(
                        "hub",
                        "session_playback_stopped",
                        session_id=self._player_session_id,
                        pid=process.pid,
                    )
                )
                return
            if self._player_temp_path is not None:
                self._player_temp_path.unlink(missing_ok=True)
                self._player_temp_path = None
            mixed_path = self._write_mixed_audio(session_id)
            try:
                process = self._player_factory(["pw-play", str(mixed_path)])
            except Exception:
                mixed_path.unlink(missing_ok=True)
                raise
            self._player = process
            self._player_pid = process.pid
            self._player_session_id = session_id
            self._player_temp_path = mixed_path
            log.info(
                fmt_event("hub", "session_playback_started", session_id=session_id, pid=process.pid)
            )
            threading.Thread(
                target=self._watch_player,
                args=(process, mixed_path, session_id),
                name="stenographer-session-player",
                daemon=True,
            ).start()

    def stop_session_playback(self) -> None:
        with self._player_lock:
            if self._player is not None and self._player.poll() is None:
                if self._player_pid is None or self._player.pid != self._player_pid:
                    raise RuntimeError("session player process identity changed")
                self._player.terminate()
                log.info(
                    fmt_event(
                        "hub",
                        "session_playback_stopped",
                        session_id=self._player_session_id,
                        pid=self._player.pid,
                    )
                )

    def _watch_player(self, process: subprocess.Popen, mixed_path: Path, session_id: str) -> None:
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
            if self._player is process:
                self._player = None
                self._player_pid = None
                self._player_session_id = None
            if self._player_temp_path == mixed_path:
                self._player_temp_path = None
            mixed_path.unlink(missing_ok=True)

    def _write_mixed_audio(self, session_id: str) -> Path:
        directory = self.session_store.root / session_id
        paths = [directory / "mic.flac", directory / "system.flac"]
        with ExitStack() as stack:
            streams = [stack.enter_context(sf.SoundFile(path)) for path in paths if path.is_file()]
            if not streams:
                raise FileNotFoundError(f"session has no audio: {session_id}")
            sample_rate = streams[0].samplerate
            if any(stream.samplerate != sample_rate for stream in streams):
                raise ValueError("session audio sources use different sample rates")
            total_frames = max(stream.frames for stream in streams)
            fd, name = tempfile.mkstemp(prefix="stenographer-session-", suffix=".wav")
            os.close(fd)
            mixed_path = Path(name)
            try:
                with sf.SoundFile(
                    mixed_path,
                    mode="w",
                    samplerate=sample_rate,
                    channels=1,
                    format="WAV",
                    subtype="PCM_16",
                ) as output:
                    for start in range(0, total_frames, 65_536):
                        count = min(65_536, total_frames - start)
                        mixed = np.zeros(count, dtype=np.float32)
                        for stream in streams:
                            available = min(count, max(0, stream.frames - start))
                            if available:
                                stream.seek(start)
                                samples = stream.read(available, dtype="float32", always_2d=True)
                                mixed[: len(samples)] += np.mean(samples, axis=1, dtype=np.float32)
                        output.write(np.clip(mixed, -1.0, 1.0))
            except Exception:
                mixed_path.unlink(missing_ok=True)
                raise
        return mixed_path

    def cancel_files(self) -> None:
        engine = self._files_engine
        if engine is not None:
            self.close_files()
            return
        job = self.files_job
        if job is not None:
            job.cancel()
            self.files_job = None
