# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure reductions for 500 ms resource observations supplied by a host provider."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class ResourceSummary:
    started_at: float
    ended_at: float | None = None
    observations: int = 0
    boundary_requests: int = 0
    boundary_samples: int = 0
    failures: int = 0
    first_cpu: float | None = None
    last_cpu: float | None = None
    cpu_samples: int = 0
    intervals: set[int] = field(default_factory=set)
    values: dict[str, tuple[int, float, float]] = field(default_factory=dict)
    unavailable: set[str] = field(default_factory=set)

    def observe(self, observation: Mapping[str, object], *, observed_at: float) -> bool:
        # A probe can begin while active and finish after terminal acceptance.
        # Never attribute that later observation to the completed utterance.
        if observed_at < self.started_at or (
            self.ended_at is not None and observed_at > self.ended_at
        ):
            return False
        self.observations += 1
        self.intervals.add(max(0, math.floor((observed_at - self.started_at) / 0.5)))
        reasons = observation.get("reasons")
        if isinstance(reasons, Mapping):
            for key, value in reasons.items():
                if key in (
                    "app",
                    "application",
                    "host",
                    "host_cpu",
                    "gpu",
                    "cpu_seconds",
                    "resident_bytes",
                    "host_cpu_percent",
                    "host_memory_used_bytes",
                    "gpu_utilization_percent",
                    "gpu_memory_used_bytes",
                ):
                    # Only fixed categories are retained, never a provider exception message.
                    reason = (
                        value
                        if value
                        in (
                            "unsupported",
                            "unavailable",
                            "permission_denied",
                            "dependency_missing",
                            "not_supported",
                            "process_unavailable",
                            "probe_failed",
                            "shared_memory",
                            "registered_process_unavailable",
                            "baseline_required",
                            "host_probe_unavailable",
                            "gpu_probe_failed",
                            "gpu_unavailable_shared_memory_is_not_vram",
                            "native_gpu_probe_unavailable",
                        )
                        else "unavailable"
                    )
                    self.unavailable.add(f"{key}:{reason}")
        cpu = observation.get("cpu_seconds")
        if isinstance(cpu, (int, float)) and math.isfinite(cpu) and cpu >= 0:
            self.cpu_samples += 1
            if self.first_cpu is None:
                self.first_cpu = float(cpu)
            self.last_cpu = float(cpu)
        for key in (
            "resident_bytes",
            "host_cpu_percent",
            "host_memory_used_bytes",
            "gpu_utilization_percent",
            "gpu_memory_used_bytes",
        ):
            # The provider's first percentage may span idle time since its last
            # observation of the previous utterance. This window needs a baseline.
            if key == "host_cpu_percent" and self.observations == 1:
                continue
            value = observation.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                continue
            count, total, maximum = self.values.get(key, (0, 0.0, 0.0))
            self.values[key] = (count + 1, total + value, max(maximum, value))
        return True

    def context(self) -> dict[str, str]:
        if not self.observations:
            return {"resource_availability": "sampling:no_timely_samples"}
        if not self.unavailable:
            return {}
        return {"resource_availability": ",".join(sorted(self.unavailable))[:256]}

    def metrics(self, now: float) -> dict[str, int | float]:
        if self.ended_at is not None:
            now = min(now, self.ended_at)
        expected = max(1, math.floor(max(0, now - self.started_at) / 0.5) + 1)
        result: dict[str, int | float] = {
            "resource_samples": self.observations,
            "resource_expected_samples": expected,
            "resource_coverage": sum(index < expected for index in self.intervals) / expected,
            "resource_probe_failures": self.failures,
            "resource_window_s": max(0.0, now - self.started_at),
            "resource_boundary_samples": self.boundary_samples,
            "resource_boundary_missing": self.boundary_requests - self.boundary_samples,
            "app_cpu_samples": self.cpu_samples,
        }
        if self.cpu_samples >= 2 and self.first_cpu is not None and self.last_cpu is not None:
            result["app_cpu_s"] = max(0, self.last_cpu - self.first_cpu)
        for source, target, coverage, average in (
            ("resident_bytes", "app_rss_bytes_max", "app_memory_samples", False),
            ("host_cpu_percent", "host_cpu_percent_avg", "host_cpu_samples", True),
            ("host_memory_used_bytes", "host_memory_used_bytes_max", "host_memory_samples", False),
            (
                "gpu_utilization_percent",
                "gpu_utilization_percent_avg",
                "gpu_utilization_samples",
                True,
            ),
            ("gpu_memory_used_bytes", "gpu_memory_used_bytes_max", "gpu_memory_samples", False),
        ):
            count, total, maximum = self.values.get(source, (0, 0, 0))
            result[coverage] = count
            if count:
                result[target] = total / count if average else maximum
        return result
