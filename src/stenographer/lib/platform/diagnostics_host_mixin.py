# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import platform

from stenographer.lib.platform.resource_probe import ResourceProbe


class DiagnosticsHostMixin:
    """Host operations shared by providers; backend modules stay lazy."""

    def resource_probe(self):
        return ResourceProbe()

    def process_identity(self) -> tuple[int, float]:
        import psutil

        process = psutil.Process()
        return process.pid, process.create_time()

    def process_alive(self, pid: int, started_epoch: float) -> bool | None:
        import psutil

        try:
            process = psutil.Process(pid)
            return process.create_time() == started_epoch and process.is_running()
        except psutil.NoSuchProcess:
            return False
        except (psutil.AccessDenied, OSError):
            return None

    def runtime_context(self) -> dict[str, str]:
        return {
            "os": platform.system(),
            "os_version": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
        }
