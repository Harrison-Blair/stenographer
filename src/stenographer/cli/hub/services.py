# SPDX-License-Identifier: GPL-3.0-or-later
"""Own long-lived work shared by hub sections."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from stenographer.lib.live.live_session import LiveSession
from stenographer.lib.live.models import LIVE_MODELS

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform


class HubServices:
    """Keep recording and Files work independent of the selected section."""

    def __init__(
        self,
        config: Config,
        platform: Platform,
        *,
        session_factory: Callable[..., LiveSession] = LiveSession,
    ) -> None:
        self._config = config
        self._platform = platform
        self._session_factory = session_factory
        self._session: LiveSession | None = None
        self.files_job = None

    @property
    def recording(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> LiveSession | None:
        return self._session

    def update_config(self, config: Config) -> None:
        """Use saved settings for new work without changing an active session."""

        self._config = config

    @property
    def files_running(self) -> bool:
        return self.files_job is not None

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

    def cancel_files(self) -> None:
        job = self.files_job
        if job is None:
            return
        job.cancel()
        self.files_job = None
