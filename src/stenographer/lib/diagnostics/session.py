# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect configuration and host services to analytics sessions."""

from __future__ import annotations

import contextlib
import re
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from stenographer.lib.config.models import Config
    from stenographer.lib.platform.platform import Platform

from stenographer.lib.diagnostics.collection import Collection
from stenographer.lib.transcribe.bark_download import MODEL_DIRNAME


def technical_context(cfg: Config) -> dict[str, str | int]:
    """Retain configured identifiers, substituting fixed labels for path-valued settings."""
    device = cfg.audio.input_device or "default"
    if device.startswith(("/", "\\", ".")) or re.match(r"^[A-Za-z]:[\\/]", device):
        device = "configured_device"
    return {
        "model": MODEL_DIRNAME,
        "device": device[:256],
        "mode": cfg.hotkey.mode,
    }


def _create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    from stenographer._version import __version__
    from stenographer.lib.analytics.session import AnalyticsSession
    from stenographer.lib.analytics.store import database_path
    from stenographer.lib.transcribe.decode import resolve_cpu_threads

    context = {
        **technical_context(cfg),
        **platform.runtime_context(),
        "app_version": __version__,
        "cpu_threads": resolve_cpu_threads(platform.physical_core_count()),
    }
    with contextlib.suppress(PackageNotFoundError):
        context["runtime_version"] = version("sherpa-onnx")
    probe = platform.resource_probe()
    identity = None
    with contextlib.suppress(Exception):
        identity = platform.process_identity()
    return AnalyticsSession(
        database_path(platform),
        context=context,
        resource_probe=(lambda: probe(pids())) if probe is not None else None,
        process_identity=identity,
        process_alive=platform.process_alive,
    )


def create_session(cfg: Config, platform: Platform, *, pids: Callable[[], Sequence[int]] = tuple):
    if not cfg.analytics.enabled:
        return Collection()
    try:
        return Collection(session=_create_session(cfg, platform, pids=pids))
    except Exception:
        return Collection()
