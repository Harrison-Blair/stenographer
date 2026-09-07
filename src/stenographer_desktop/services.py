# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless adapters used by desktop workers; never import CLI handlers."""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import threading
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from stenographer.config import Config, ConfigError
from stenographer.platform import current_platform
from stenographer.settings import ConfigDocument
from stenographer.utils.logging_setup import log_failure

logger = logging.getLogger(__name__)


def edited_config(document: ConfigDocument, edits: Mapping[str, object]) -> Config:
    """Validate form values through the same TOML schema as every other frontend."""
    import tomlkit

    values = dataclasses.asdict(document.config)
    content = tomlkit.parse(document.render(document.config))
    for dotted, raw in edits.items():
        section, key = dotted.split(".", 1)
        original = values[section][key]
        if isinstance(raw, str) and isinstance(original, (int, float, tuple)):
            try:
                value = tomllib.loads(f"value = {raw}")["value"]
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(document.path, dotted, "enter a valid number or array") from exc
        else:
            value = raw
        content["stenographer"][section][key] = value
    return Config.loads(tomlkit.dumps(content), document.path)


def flatten(value: object, prefix: str = "") -> list[tuple[str, str]]:
    """Readable numeric/structural report rows, preserving unavailable values."""
    if isinstance(value, dict):
        return [
            row
            for key, item in value.items()
            for row in flatten(item, f"{prefix}.{key}" if prefix else str(key))
        ]
    if isinstance(value, (list, tuple)):
        return [
            row for index, item in enumerate(value) for row in flatten(item, f"{prefix}[{index}]")
        ]
    return [(prefix, "Unavailable" if value is None else str(value))]


class DesktopServices:
    """Own the desktop's control session; its closure releases maintenance."""

    def __init__(self, config_path: Path, database_path: Path | None = None) -> None:
        self.config_path = config_path
        self.database_path = database_path
        self.platform = current_platform()
        self._client: Any = None
        self._lock = threading.RLock()
        self._maintenance_lock = threading.Lock()
        self._maintenance_cancel: threading.Event | None = None
        self._lease_client: Any = None

    def close(self) -> None:
        # Signal first: active capture must stop before waiting for a pending request.
        cancellation = self._maintenance_cancel
        if cancellation is not None:
            cancellation.set()
        with self._lock:
            self._disconnect()

    def _disconnect(self) -> None:
        if self._lease_client is not None and self._maintenance_cancel is not None:
            self._maintenance_cancel.set()
        if self._client is not None:
            self._client.close()
            self._client = None

    def control(self, action: str, payload: dict | None = None) -> dict:
        from stenographer.control import ControlClient

        with self._lock:
            if self._client is None:
                self._client = ControlClient(platform=self.platform)
            try:
                response = self._client.request(action, payload)
                if action == "status" and self._lease_client is not None:
                    status = response.get("status", {})
                    if not response.get("ok") or status.get("lifecycle") != "maintenance":
                        self._maintenance_cancel.set()
                return response
            except Exception:
                self._disconnect()
                raise

    def status(self) -> dict:
        try:
            return self.control("status")
        except (OSError, EOFError, ConnectionError):
            return {"ok": False, "reason": "Daemon unavailable", "status": {"lifecycle": "stopped"}}

    def store(self):
        from stenographer.analytics import Store, database_path

        return Store(self.database_path or database_path())

    def load_settings(self) -> tuple[ConfigDocument, tuple[str, ...] | None]:
        """Load settings and validate sound-pack choices together on one worker."""
        from stenographer.delivery.feedback import discover_sound_packs

        document = ConfigDocument.load(self.config_path)
        try:
            packs = discover_sound_packs(self.config_path.parent)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "desktop: sound_pack_discovery_failed",
                exc,
                safe=False,
            )
            packs = None
        return document, packs

    def report(self, filters=None) -> dict:
        from stenographer.analytics import Filters

        return self.store().report(filters or Filters())

    @contextlib.contextmanager
    def maintenance(self, kind: str) -> Iterator[threading.Event]:
        """Use an authoritative daemon lease whenever it is running."""
        if not self._maintenance_lock.acquire(blocking=False):
            raise RuntimeError("Another setup operation is active.")
        cancellation = threading.Event()
        self._maintenance_cancel = cancellation
        try:
            with self._daemon_maintenance(kind):
                yield cancellation
        finally:
            with self._lock:
                cancellation.set()
                self._maintenance_cancel = None
                self._lease_client = None
            self._maintenance_lock.release()

    @contextlib.contextmanager
    def _daemon_maintenance(self, kind: str) -> Iterator[None]:
        try:
            # Registration and admission are atomic with respect to heartbeat requests.
            with self._lock:
                response = self.control("maintenance_begin", {"kind": kind})
                if not response.get("ok"):
                    raise RuntimeError(response.get("reason", "Maintenance unavailable"))
                self._lease_client = self._client
        except (FileNotFoundError, ConnectionRefusedError):
            # Hold the daemon instance lock so it cannot start during local setup.
            from stenographer.platform.base import UnsupportedPlatformError

            try:
                lock = self.platform.single_instance_lock()
            except UnsupportedPlatformError:
                # Providers without dictation cannot race a local setup capture.
                yield
                return
            if not lock.acquire():
                raise RuntimeError("The daemon is starting; retry setup when it is idle.") from None
            try:
                yield
            finally:
                lock.release()
            return
        try:
            yield
        finally:
            with self._lock:
                # Never release a different session after reconnecting a failed lease.
                if self._lease_client is self._client and self._client is not None:
                    with contextlib.suppress(Exception):
                        self.control("maintenance_end")

    def service_action(self, action: str) -> tuple[bool, str]:
        if action in {"stop", "restart", "apply"}:
            try:
                result = self.control(action)
            except (FileNotFoundError, ConnectionRefusedError):
                if action == "apply":
                    return False, "Daemon is stopped; saved settings load on its next start."
                return False, "Daemon control unavailable; Start can launch a stopped service."
            else:
                return bool(result.get("ok")), str(result.get("reason", "Action accepted"))
        return self.platform.service_action(action)

    def preview(self, cfg: Config) -> str:
        from stenographer.delivery.feedback import (
            load_sound_pack,
            preview_sound_pack,
            preview_volume,
        )

        with self.maintenance("sound") as cancellation:
            player = self.platform.cue_player()
            pack = load_sound_pack(cfg.feedback.sound_pack, self.config_path.parent)
            if player is None or pack is None:
                raise RuntimeError("The selected sound pack or sound player is unavailable.")
            preview_sound_pack(
                pack, player, preview_volume(cfg.feedback), cancellation=cancellation
            )
        return "Sound preview complete."


def comparison_rows(records: list[dict], group: str, metric: str) -> list[tuple]:
    """Compare matching raw utterances, including unknown measurements in coverage."""
    from stenographer.analytics.metrics import distribution

    groups: dict[str, list] = {}
    for record in records:
        groups.setdefault(str(record["context"].get(group, "Unavailable")), []).append(
            record["metrics"].get(metric)
        )
    rows = []
    for name, values in sorted(groups.items()):
        summary = distribution(values)
        rows.append(
            (name, *(summary[key] for key in ("count", "missing", "average", "p95", "p99")))
        )
    return rows


def histogram_rows(records: list[dict], metric: str, bins: int = 10) -> list[tuple]:
    """Counts in bounded equal-width bins; absent observations are not zero."""
    values = [row["metrics"][metric] for row in records if metric in row["metrics"]]
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [(f"{low:g}", len(values))]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        counts[min(int((value - low) / width), bins - 1)] += 1
    return [
        (f"{low + index * width:.2f} to {low + (index + 1) * width:.2f}", count)
        for index, count in enumerate(counts)
    ]
