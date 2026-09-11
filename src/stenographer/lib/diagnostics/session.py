# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect configuration and host services to analytics sessions."""

from __future__ import annotations

import contextlib
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform

from stenographer.lib.diagnostics.collection import Collection
from stenographer.lib.diagnostics.context import technical_context


def _create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    from stenographer._version import __version__
    from stenographer.lib.analytics.session import AnalyticsSession
    from stenographer.lib.transcribe.decode import resolve_cpu_threads

    context = {
        **technical_context(cfg),
        **platform.runtime_context(),
        "app_version": __version__,
        "cpu_threads": resolve_cpu_threads(cfg.asr.cpu_threads, platform.physical_core_count()),
    }
    with contextlib.suppress(PackageNotFoundError):
        context["runtime_version"] = version("faster-whisper")
    probe = (
        platform.resource_probe()
        if cfg.analytics.resource_profiling and cfg.analytics.enabled
        else None
    )
    identity = None
    with contextlib.suppress(Exception):
        identity = platform.process_identity()
    return AnalyticsSession(
        platform.state_dir(os.environ, Path.home()) / "analytics.sqlite3",
        context=context,
        enabled=cfg.analytics.enabled,
        resource_probe=(lambda: probe(pids())) if probe is not None else None,
        process_identity=identity,
        process_alive=platform.process_alive,
    )


def create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    if not cfg.analytics.enabled:
        return Collection(enabled=False)
    try:
        return Collection(enabled=True, session=_create_session(cfg, platform, pids=pids))
    except Exception:
        return Collection(enabled=True, failures=1)
