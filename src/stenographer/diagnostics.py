# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless analytics wiring; no frontend handlers and no host introspection."""

from __future__ import annotations

import contextlib
import os
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stenographer.config import Config
    from stenographer.platform.base import Platform


def technical_context(cfg: Config) -> dict[str, str | int]:
    """Retain configured identifiers, substituting fixed labels for path-valued settings."""
    model = cfg.asr.model
    if re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", model) is None or model.startswith("."):
        model = "local_model"
    device = cfg.audio.input_device or "default"
    if device.startswith(("/", "\\", ".")) or re.match(r"^[A-Za-z]:[\\/]", device):
        device = "configured_device"
    return {
        "model": model,
        "device": device[:256],
        "compute_type": cfg.asr.compute_type,
        "mode": cfg.hotkey.mode,
    }


def _create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    from stenographer._version import __version__
    from stenographer.analytics import AnalyticsSession
    from stenographer.transcribe.model import resolve_cpu_threads

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


class Collection:
    """Fail-open instrumentation facade shared by both transcription entry points."""

    def __init__(self, *, enabled: bool, session=None, failures: int = 0):
        self.enabled = enabled
        self._session = session
        self._failures = failures

    @property
    def health(self) -> dict:
        health = self._session.health if self._session is not None else {}
        return {
            **health,
            "enabled": self.enabled,
            "degraded": bool(self._failures or health.get("degraded")),
            "dropped_checkpoints": self._failures + health.get("dropped_checkpoints", 0),
        }

    def _call(self, method, *args, **kwargs):
        if self._session is None:
            return None
        try:
            return getattr(self._session, method)(*args, **kwargs)
        except Exception:
            self._failures += 1
            return None

    def start(self, utterance_id, **kwargs):
        return self._call("start", utterance_id, **kwargs)

    def checkpoint(self, identity, phase, metrics=None, **kwargs):
        if identity is not None:
            self._call("checkpoint", identity, phase, metrics, **kwargs)

    def finish(self, identity, outcome, metrics=None):
        if identity is not None:
            self._call("finish", identity, outcome, metrics)

    def close(self, timeout=2.0):
        return self._call("close", timeout)


def create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    if not cfg.analytics.enabled:
        return Collection(enabled=False)
    try:
        return Collection(enabled=True, session=_create_session(cfg, platform, pids=pids))
    except Exception:
        return Collection(enabled=True, failures=1)
