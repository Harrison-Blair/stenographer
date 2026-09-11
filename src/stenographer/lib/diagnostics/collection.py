# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-open instrumentation shared by dictation and file transcription."""

from __future__ import annotations


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
