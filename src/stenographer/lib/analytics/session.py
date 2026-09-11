# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded asynchronous checkpoints: persistence never waits in the hot path.

Each measurements payload is a cumulative immutable snapshot. Queue overflow can therefore
lose intermediate checkpoints without double counting subsequent snapshots.
The writer retries transient SQLite contention a bounded number of times and
keeps an in-memory health signal even when no database write is possible.
Queued payloads share a private resource window closed at terminal acceptance,
so deferred persistence never samples or attributes post-utterance activity.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from stenographer.lib.analytics.checkpoint_records import Checkpoint, QueuedCheckpoint
from stenographer.lib.analytics.checkpoints import advance_checkpoint
from stenographer.lib.analytics.metrics import (
    OUTCOMES,
    PHASES,
    clean_context,
    clean_metrics,
    utc_now,
)
from stenographer.lib.analytics.resources import ResourceSummary
from stenographer.lib.analytics.store import Store


class AnalyticsSession:
    def __init__(
        self,
        path: Path,
        *,
        context: Mapping[str, object] | None = None,
        enabled: bool = True,
        resource_probe: Callable[[], Mapping[str, object]] | None = None,
        queue_size: int = 128,
        retries: int = 3,
        process_identity: tuple[int, float] | None = None,
        process_alive: Callable[[int, float], bool | None] | None = None,
    ) -> None:
        self.run_id = str(uuid.uuid4())
        self.enabled = enabled
        self.context = clean_context(context or {})
        self._store = Store(path)
        self._probe = resource_probe
        self._process_identity = process_identity
        self._process_alive = process_alive
        self._retries = max(0, retries)
        self._queue: queue.Queue[QueuedCheckpoint] = queue.Queue(maxsize=max(1, queue_size))
        self._lock = threading.Lock()
        self._records: dict[str, QueuedCheckpoint] = {}
        self._terminal_queued: set[str] = set()
        self._health = {"degraded": False, "dropped_checkpoints": 0, "write_failures": 0}
        self._closing = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled:
            self._thread = threading.Thread(target=self._run, name="analytics-writer", daemon=True)
            self._thread.start()

    @property
    def health(self) -> dict[str, Any]:
        with self._lock:
            return {"enabled": self.enabled, **self._health, "pending": self._queue.qsize()}

    def start(
        self,
        utterance_id: str | int,
        *,
        source: str = "hotkey",
        context: Mapping[str, object] | None = None,
    ) -> str:
        identity = f"{self.run_id}:{utterance_id}"
        if not self.enabled:
            return identity
        if source not in ("hotkey", "file"):
            raise ValueError("Only personal hotkey and file transcription are collected")
        timestamp = utc_now()
        checkpoint = Checkpoint(
            id=identity,
            run_id=self.run_id,
            source=source,
            started_at=timestamp,
            updated_at=timestamp,
            context={**self.context, **clean_context(context or {})},
            monotonic_started=time.monotonic(),
        )
        record = QueuedCheckpoint(
            checkpoint,
            ResourceSummary(checkpoint.monotonic_started) if self._probe is not None else None,
        )
        with self._lock:
            if self._closing.is_set():
                return identity
            if identity in self._records:
                raise ValueError("Utterance identity has already started")
            self._records[identity] = record
            self._enqueue(record)
        return identity

    def checkpoint(
        self,
        utterance_id: str | int,
        phase: str,
        metrics: Mapping[str, object] | None = None,
        *,
        outcome: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        if not self.enabled:
            return
        if phase not in PHASES:
            raise ValueError("Unknown analytics checkpoint phase")
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError("Invalid analytics outcome")
        measurements = clean_metrics(metrics or {})
        technical = clean_context(context or {})
        identity = str(utterance_id)
        if not identity.startswith(f"{self.run_id}:"):
            identity = f"{self.run_id}:{identity}"
        with self._lock:
            old = self._records.get(identity)
            if old is None or self._closing.is_set():
                return
            checkpoint = advance_checkpoint(
                old.checkpoint,
                phase,
                updated_at=utc_now(),
                monotonic_now=time.monotonic(),
                metrics=measurements,
                context=technical,
                outcome=outcome,
            )
            record = QueuedCheckpoint(checkpoint, old.resource)
            if phase == "terminal" and record.resource is not None:
                record.resource.ended_at = checkpoint.monotonic_finished
            self._records[identity] = record
            queued = self._enqueue(record)
            if phase == "terminal":
                if queued:
                    self._terminal_queued.add(identity)
                del self._records[identity]

    def finish(
        self,
        utterance_id: str | int,
        outcome: str,
        metrics: Mapping[str, object] | None = None,
    ) -> None:
        self.checkpoint(utterance_id, "terminal", metrics, outcome=outcome)

    def _enqueue(self, record: QueuedCheckpoint) -> bool:
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            self._health["degraded"] = True
            self._health["dropped_checkpoints"] += 1
            return False

    def _attempt(self, operation: Callable[[], Any]) -> bool:
        for attempt in range(self._retries + 1):
            try:
                operation()
                return True
            except (sqlite3.Error, OSError, ValueError):
                if attempt < self._retries:
                    time.sleep(0.025 * (attempt + 1))
        with self._lock:
            self._health["degraded"] = True
            self._health["write_failures"] += 1
        return False

    def _observe(self, summary: ResourceSummary) -> bool:
        if self._probe is None or summary.ended_at is not None:
            return False
        try:
            return summary.observe(self._probe(), observed_at=time.monotonic())
        except Exception:
            # Provider exceptions may contain host details; never log or retain them.
            summary.failures += 1
            return False

    def _run(self) -> None:
        registered = self._attempt(
            lambda: self._store.register_run(
                self.run_id,
                self.context,
                self._process_identity,
            )
        )
        if self._process_alive is not None:
            self._attempt(lambda: self._store.recover_interrupted(self._process_alive))
        active: dict[str, ResourceSummary] = {}
        last_sample = time.monotonic()
        while not self._closing.is_set() or not self._queue.empty():
            try:
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                record = None
            now = time.monotonic()
            with self._lock:
                recording = set(self._records)
                pending = recording | self._terminal_queued
            active = {
                identity: summary for identity, summary in active.items() if identity in pending
            }
            if now - last_sample >= 0.5:
                for identity, summary in active.items():
                    if identity in recording:
                        self._observe(summary)
                last_sample = now
            if record is None:
                continue
            if not registered:
                registered = self._attempt(
                    lambda: self._store.register_run(
                        self.run_id,
                        self.context,
                        self._process_identity,
                    )
                )
            payload = record.checkpoint.to_store()
            if record.resource is not None:
                summary = active.setdefault(record.checkpoint.id, record.resource)
                summary.boundary_requests += 1
                summary.boundary_samples += int(self._observe(summary))
                payload["metrics"].update(summary.metrics(time.monotonic()))
                payload["context"].update(summary.context())
            if not self._attempt(lambda payload=payload: self._store.write_checkpoint(payload)):
                with self._lock:
                    self._health["dropped_checkpoints"] += 1
            if record.checkpoint.phase == "terminal":
                active.pop(record.checkpoint.id, None)
                with self._lock:
                    self._terminal_queued.discard(record.checkpoint.id)
            self._queue.task_done()
            self._attempt(lambda: self._store.update_health(self.run_id, self.health))
        self._attempt(lambda: self._store.update_health(self.run_id, self.health, ended=True))

    def close(self, timeout: float = 2.0) -> bool:
        """Bounded flush; return whether pending writes drained before the deadline."""
        with self._lock:
            now = time.monotonic()
            for record in self._records.values():
                if record.resource is not None:
                    record.resource.ended_at = now
            self._closing.set()
        if self._thread is None:
            return True
        self._thread.join(max(0, timeout))
        return not self._thread.is_alive()
