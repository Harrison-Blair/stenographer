# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared host adapters for resource profiling and process diagnostics."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


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


class ResourceProbe:
    """Sample only registered processes and anonymous host aggregates.

    psutil performs native host calls. CPU utilization needs two observations;
    the first is unknown. Missing process samples never masquerade as zero.
    GPU data comes from bounded NVIDIA queries or Linux aggregate sysfs metrics.
    CPU totals accumulate observations by process identity so retiring a child
    cannot subtract work. Work after its final observation remains unmeasured.
    """

    def __init__(self):
        self._host_cpu = None
        self._process_cpu: dict[tuple[int, float], float] = {}
        self._cpu_total = 0.0
        self._nvidia = shutil.which("nvidia-smi")

    def __call__(self, pids=()) -> dict:
        import psutil

        reasons = {}
        result = {
            "monotonic_seconds": time.monotonic(),
            "cpu_seconds": None,
            "resident_bytes": None,
            "host_cpu_percent": None,
            "host_memory_used_bytes": None,
            "host_memory_total_bytes": None,
            "gpu_utilization_percent": None,
            "gpu_memory_used_bytes": None,
            "reasons": reasons,
        }
        rss = 0
        complete = True
        for pid in {os.getpid(), *pids}:
            try:
                process = psutil.Process(pid)
                with process.oneshot():
                    times = process.cpu_times()
                    identity = (pid, process.create_time())
                    cpu = times.user + times.system
                    self._cpu_total += max(0.0, cpu - self._process_cpu.get(identity, 0.0))
                    self._process_cpu[identity] = cpu
                    rss += process.memory_info().rss
            except (psutil.Error, OSError):
                complete = False
        if complete:
            result.update(cpu_seconds=self._cpu_total, resident_bytes=rss)
        else:
            reasons["application"] = "registered_process_unavailable"
        try:
            memory = psutil.virtual_memory()
            result.update(
                host_memory_used_bytes=memory.total - memory.available,
                host_memory_total_bytes=memory.total,
            )
            times = psutil.cpu_times()
            # Linux guest times are already included in user/nice.
            total = sum(times) - getattr(times, "guest", 0) - getattr(times, "guest_nice", 0)
            idle = times.idle + getattr(times, "iowait", 0)
            if self._host_cpu is not None:
                previous_total, previous_idle = self._host_cpu
                elapsed = total - previous_total
                if elapsed > 0:
                    result["host_cpu_percent"] = max(
                        0.0, min(100.0, 100 * (1 - (idle - previous_idle) / elapsed))
                    )
            else:
                reasons["host_cpu"] = "baseline_required"
            self._host_cpu = total, idle
        except (psutil.Error, OSError):
            reasons["host"] = "host_probe_unavailable"
        gpu, reason = self._gpu()
        result.update(gpu)
        if reason:
            reasons["gpu"] = reason
        return result

    def _gpu(self) -> tuple[dict, str | None]:
        """Aggregate vendor metrics only; no process/device identities are retained."""
        if self._nvidia:
            try:
                sample = subprocess.run(
                    [
                        self._nvidia,
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=0.2,
                    check=True,
                )
                rows = [
                    tuple(float(value.strip()) for value in line.split(","))
                    for line in sample.stdout.splitlines()
                    if line.strip()
                ]
                if not rows or any(len(row) != 2 for row in rows):
                    return {}, "gpu_metrics_unavailable"
                return {
                    "gpu_utilization_percent": sum(row[0] for row in rows) / len(rows),
                    "gpu_memory_used_bytes": sum(row[1] for row in rows) * 1048576,
                }, None
            except (OSError, ValueError, subprocess.SubprocessError):
                return {}, "gpu_probe_failed"
        if sys.platform == "linux":
            devices = list(Path("/sys/class/drm").glob("card[0-9]*/device"))
            usage, memory = [], []
            for device in devices:
                try:
                    usage.append(float((device / "gpu_busy_percent").read_text()))
                    memory.append(int((device / "mem_info_vram_used").read_text()))
                except (OSError, ValueError):
                    continue
            if usage and memory and len(usage) == len(memory):
                return {
                    "gpu_utilization_percent": sum(usage) / len(usage),
                    "gpu_memory_used_bytes": sum(memory),
                }, None
        if sys.platform == "darwin":
            return {}, "gpu_unavailable_shared_memory_is_not_vram"
        return {}, "native_gpu_probe_unavailable"
