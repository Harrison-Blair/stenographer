# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared host adapters for desktop status and profiling. No GUI imports."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from stenographer.platform.base import ServiceStatus


class DesktopHostMixin:
    """Host operations shared by providers; backend modules stay lazy."""

    def control_transport(self):
        from stenographer.platform.local_control import LocalControlTransport

        return LocalControlTransport(self.state_dir(os.environ, Path.home()) / "control")

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

    def service_status(self) -> ServiceStatus:
        return ServiceStatus(False, detail=f"Service integration is unavailable on {self.name}.")

    def service_action(self, action: str) -> tuple[bool, str]:
        return False, self.service_status().detail

    def restart_running_service(self) -> tuple[bool, str]:
        return False, self.service_status().detail

    def focused_key_name(
        self, key: int, native_virtual_key: int = 0, native_scan_code: int = 0
    ) -> str | None:
        """Qt logical key values to shared binding names; imports no Qt.

        Logical values are stable Qt public constants. Left modifiers are the
        default where a window system does not provide side information.
        """
        if 65 <= key <= 90 or 48 <= key <= 57:
            return f"KEY_{chr(key)}"
        if 0x01000030 <= key <= 0x01000047:
            return f"KEY_F{key - 0x01000030 + 1}"
        names = {
            0x20: "KEY_SPACE",
            0x01000000: "KEY_ESC",
            0x01000001: "KEY_TAB",
            0x01000003: "KEY_BACKSPACE",
            0x01000004: "KEY_ENTER",
            0x01000005: "KEY_KPENTER",
            0x01000006: "KEY_INSERT",
            0x01000007: "KEY_DELETE",
            0x01000010: "KEY_HOME",
            0x01000011: "KEY_END",
            0x01000012: "KEY_LEFT",
            0x01000013: "KEY_UP",
            0x01000014: "KEY_RIGHT",
            0x01000015: "KEY_DOWN",
            0x01000016: "KEY_PAGEUP",
            0x01000017: "KEY_PAGEDOWN",
            0x01000020: "KEY_LEFTSHIFT",
            0x01000021: "KEY_LEFTCTRL",
            0x01000022: "KEY_LEFTMETA",
            0x01000023: "KEY_LEFTALT",
            0x01000024: "KEY_CAPSLOCK",
            0x01000025: "KEY_NUMLOCK",
            0x01000026: "KEY_SCROLLLOCK",
            0x2D: "KEY_MINUS",
            0x3D: "KEY_EQUAL",
            0x5B: "KEY_LEFTBRACE",
            0x5D: "KEY_RIGHTBRACE",
            0x5C: "KEY_BACKSLASH",
            0x3B: "KEY_SEMICOLON",
            0x27: "KEY_APOSTROPHE",
            0x60: "KEY_GRAVE",
            0x2C: "KEY_COMMA",
            0x2E: "KEY_DOT",
            0x2F: "KEY_SLASH",
        }
        right = {
            "windows": {
                0xA1: "KEY_RIGHTSHIFT",
                0xA3: "KEY_RIGHTCTRL",
                0xA5: "KEY_RIGHTALT",
                0x5C: "KEY_RIGHTMETA",
            },
            "linux": {
                0xFFE2: "KEY_RIGHTSHIFT",
                0xFFE4: "KEY_RIGHTCTRL",
                0xFFEA: "KEY_RIGHTALT",
                0xFE03: "KEY_RIGHTALT",
                0xFFEC: "KEY_RIGHTMETA",
            },
            "macos": {
                55: "KEY_LEFTMETA",
                59: "KEY_LEFTCTRL",
                56: "KEY_LEFTSHIFT",
                58: "KEY_LEFTALT",
                60: "KEY_RIGHTSHIFT",
                62: "KEY_RIGHTCTRL",
                61: "KEY_RIGHTALT",
                54: "KEY_RIGHTMETA",
            },
        }
        return right.get(self.name, {}).get(native_virtual_key, names.get(key))


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
