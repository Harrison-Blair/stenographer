# SPDX-License-Identifier: GPL-3.0-or-later
"""Version 1 local desktop control, independent of the lifecycle pill protocol.

The daemon serializes this policy with its lifecycle lock. A connection owns
its temporary maintenance lease. Service reservations survive disconnection.
No configuration values or transcript data travel through this protocol.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stenographer.config import Config
    from stenographer.platform.base import Platform

VERSION = 1
ACTIONS = frozenset({"status", "maintenance_begin", "maintenance_end", "stop", "restart", "apply"})
MAINTENANCE_KINDS = frozenset({"shortcut", "calibration", "sound"})


def config_fingerprint(cfg: Config) -> str:
    """Compare saved/running configurations without exposing settings over IPC."""
    return hashlib.sha256(json.dumps(asdict(cfg), sort_keys=True).encode()).hexdigest()


def valid_request(message: object) -> bool:
    if not isinstance(message, dict) or set(message) != {"version", "id", "action", "payload"}:
        return False
    valid = (
        type(message["version"]) is int
        and message["version"] == VERSION
        and isinstance(message["id"], str)
        and 0 < len(message["id"]) <= 64
        and isinstance(message["action"], str)
        and message["action"] in ACTIONS
        and isinstance(message["payload"], dict)
    )
    if not valid:
        return False
    payload = message["payload"]
    if message["action"] == "maintenance_begin":
        return (
            set(payload) == {"kind"}
            and isinstance(payload["kind"], str)
            and payload["kind"] in MAINTENANCE_KINDS
        )
    return not payload


@dataclass
class Maintenance:
    """Pure lease and disruptive-action admission; caller owns serialization."""

    owner: str | None = None
    kind: str | None = None
    action: str | None = None

    def begin(self, owner: str, kind: str, *, busy: bool) -> bool:
        if (
            busy
            or self.owner is not None
            or self.action is not None
            or kind not in MAINTENANCE_KINDS
        ):
            return False
        self.owner, self.kind = owner, kind
        return True

    def release(self, owner: str) -> bool:
        if owner != self.owner:
            return False
        self.owner = self.kind = None
        return True

    def reserve(self, action: str, *, busy: bool) -> bool:
        if busy or self.owner is not None or self.action is not None:
            return False
        if action not in {"stop", "restart", "apply"}:
            return False
        self.action = action
        return True

    @property
    def occupied(self) -> bool:
        return self.owner is not None or self.action is not None


class ControlClient:
    """One persistent connection; closing it relinquishes temporary maintenance."""

    def __init__(self, platform: Platform | None = None) -> None:
        if platform is None:
            from stenographer.platform import current_platform

            platform = current_platform()
        self._transport = platform.control_transport()
        self._connection = None
        self._lock = threading.Lock()

    def request(self, action: str, payload: dict | None = None) -> dict:
        message = {
            "version": VERSION,
            "id": uuid.uuid4().hex,
            "action": action,
            "payload": payload or {},
        }
        if not valid_request(message):
            raise ValueError("invalid control request")
        with self._lock:
            if self._connection is None:
                self._connection = self._transport.connect()
            try:
                response = self._connection.request(message)
                if (
                    not isinstance(response, dict)
                    or type(response.get("version")) is not int
                    or response.get("version") != VERSION
                    or response.get("id") != message["id"]
                    or type(response.get("ok")) is not bool
                ):
                    raise ValueError("stale or malformed control response")
                return response
            except Exception:
                self._connection.close()
                self._connection = None
                raise

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> ControlClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
