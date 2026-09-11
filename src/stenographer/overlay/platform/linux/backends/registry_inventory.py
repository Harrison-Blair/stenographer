# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from stenographer.overlay.platform.linux.backends.global_record import _Global
from stenographer.overlay.platform.linux.backends.wayland_constants import (
    _REQUIRED_VERSIONS,
    REQUIRED_GLOBALS,
)


class RegistryInventory:
    """Pure global-registry inventory used by probing and hotplug handling."""

    def __init__(self) -> None:
        self._by_name: dict[int, _Global] = {}

    def add(self, name: int, interface: str, version: int) -> None:
        self._by_name[name] = _Global(name, interface, version)

    def remove(self, name: int) -> _Global | None:
        return self._by_name.pop(name, None)

    def get(self, interface: str) -> _Global | None:
        return next((item for item in self._by_name.values() if item.interface == interface), None)

    def version(self, interface: str) -> int:
        item = self.get(interface)
        return item.version if item is not None else 0

    def missing_required(self) -> tuple[str, ...]:
        return tuple(
            interface
            for interface in REQUIRED_GLOBALS
            if self.version(interface) < _REQUIRED_VERSIONS[interface]
        )

    def values(self) -> tuple[_Global, ...]:
        return tuple(self._by_name.values())
