# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared diagnostics test doubles."""


class AnalyticsHost:
    """Host double for session assembly: a real state directory under tmp."""

    name = "test"

    def __init__(
        self,
        state_dir,
        *,
        broken: bool = False,
        cpu_seconds: float = 0.25,
        resident_bytes: int = 2048,
    ) -> None:
        self._state_dir = state_dir
        self._broken = broken
        self._cpu_seconds = cpu_seconds
        self._resident_bytes = resident_bytes
        self.probed: list[tuple[int, ...]] = []

    def state_dir(self, env, home):
        return self._state_dir

    def runtime_context(self):
        if self._broken:
            raise OSError("host refused to describe itself")
        return {"os": "test", "architecture": "test64"}

    def physical_core_count(self):
        return 2

    def resource_probe(self):
        def probe(pids):
            self.probed.append(tuple(pids))
            return {"cpu_seconds": self._cpu_seconds, "resident_bytes": self._resident_bytes}

        return probe

    def process_identity(self):
        return (4242, 1000.0)

    def process_alive(self, pid, started_epoch):
        return None
