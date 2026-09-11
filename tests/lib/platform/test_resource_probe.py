# SPDX-License-Identifier: GPL-3.0-or-later
"""Host and process resource sampling against real psutil and a real vendor tool.

psutil samples this interpreter and this host for real. The NVIDIA branch runs
a real ``nvidia-smi`` script written into a temporary directory that is placed
on ``PATH``, so the CSV parse, the bounded timeout and every failure branch are
exercised through a genuine subprocess rather than a stubbed one.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

import pytest

from stenographer.lib.platform.resource_probe import ResourceProbe

_ARGS_LOG = "nvidia-smi.args"

#: The stand-in vendor tool is a real ``/bin/sh`` script.
_posix_shell_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the stand-in nvidia-smi is a POSIX shell script"
)


def _nvidia_smi(tmp_path: pathlib.Path, body: str, *, shebang: str = "#!/bin/sh") -> pathlib.Path:
    """Write a real executable ``nvidia-smi`` and put its directory on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "nvidia-smi"
    script.write_text(f'{shebang}\nprintf "%s\\n" "$@" > "{tmp_path / _ARGS_LOG}"\n{body}\n')
    script.chmod(0o755)
    return bin_dir


def _probe_with_nvidia(monkeypatch, tmp_path, body, *, shebang="#!/bin/sh") -> dict:
    bin_dir = _nvidia_smi(tmp_path, body, shebang=shebang)
    # Ahead of the host's own PATH, so this script is the one that is found
    # while the script itself still has the usual utilities available.
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return ResourceProbe()()


@_posix_shell_only
def test_gpu_metrics_are_averaged_utilization_and_summed_megabytes(monkeypatch, tmp_path):
    sample = _probe_with_nvidia(monkeypatch, tmp_path, 'echo "12, 2048"\necho "20, 1024"\necho ""')

    assert sample["gpu_utilization_percent"] == pytest.approx(16.0)
    assert sample["gpu_memory_used_bytes"] == 3072 * 1048576
    assert "gpu" not in sample["reasons"]


@_posix_shell_only
def test_the_gpu_query_asks_only_for_anonymous_aggregates(monkeypatch, tmp_path):
    _probe_with_nvidia(monkeypatch, tmp_path, 'echo "12, 2048"')

    assert (tmp_path / _ARGS_LOG).read_text().splitlines() == [
        "--query-gpu=utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ]


@_posix_shell_only
@pytest.mark.parametrize("body", ['echo "12"', "true", 'echo "12, 2048, 7"'])
def test_unexpected_csv_shapes_report_unavailable_rather_than_a_number(monkeypatch, tmp_path, body):
    sample = _probe_with_nvidia(monkeypatch, tmp_path, body)

    assert sample["gpu_utilization_percent"] is None
    assert sample["gpu_memory_used_bytes"] is None
    assert sample["reasons"]["gpu"] == "gpu_metrics_unavailable"


@_posix_shell_only
def test_unparseable_values_are_a_probe_failure(monkeypatch, tmp_path):
    sample = _probe_with_nvidia(monkeypatch, tmp_path, 'echo "N/A, [Not Supported]"')

    assert sample["gpu_utilization_percent"] is None
    assert sample["reasons"]["gpu"] == "gpu_probe_failed"


@_posix_shell_only
def test_a_nonzero_exit_status_is_a_probe_failure(monkeypatch, tmp_path):
    sample = _probe_with_nvidia(monkeypatch, tmp_path, 'echo "12, 2048"\nexit 9')

    assert sample["reasons"]["gpu"] == "gpu_probe_failed"


@_posix_shell_only
def test_an_unlaunchable_vendor_tool_is_a_probe_failure(monkeypatch, tmp_path):
    sample = _probe_with_nvidia(monkeypatch, tmp_path, "true", shebang="#!/nonexistent/interpreter")

    assert sample["reasons"]["gpu"] == "gpu_probe_failed"


@_posix_shell_only
def test_a_hanging_vendor_tool_cannot_stall_the_sample(monkeypatch, tmp_path):
    started_at = time.monotonic()

    sample = _probe_with_nvidia(monkeypatch, tmp_path, "sleep 30")
    elapsed = time.monotonic() - started_at

    assert sample["reasons"]["gpu"] == "gpu_probe_failed"
    # The child really was still running when the sample gave up on it, and
    # the wait is bounded far below the daemon's sampling interval.
    assert 0.1 <= elapsed < 5.0


def test_an_unknown_process_makes_the_whole_application_sample_incomplete(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    probe = ResourceProbe()

    sample = probe((999_999_999,))

    # A missing child never masquerades as zero usage for the registered set.
    assert sample["cpu_seconds"] is None
    assert sample["resident_bytes"] is None
    assert sample["reasons"]["application"] == "registered_process_unavailable"
    assert sample["host_memory_total_bytes"] > 0


def test_registered_process_cpu_accumulates_and_memory_is_measured(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    probe = ResourceProbe()

    first = probe()
    second = probe((os.getpid(),))

    assert first["cpu_seconds"] is not None
    assert first["resident_bytes"] > 0
    # Sampling this interpreter twice (once implicitly, once as a registered
    # pid) must not double-count its accumulated CPU time.
    assert second["cpu_seconds"] >= first["cpu_seconds"]
    assert second["cpu_seconds"] < first["cpu_seconds"] + 5.0
    assert second["monotonic_seconds"] >= first["monotonic_seconds"]


def test_host_cpu_percent_needs_a_baseline_before_it_can_be_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    probe = ResourceProbe()

    first = probe()

    assert first["host_cpu_percent"] is None
    assert first["reasons"]["host_cpu"] == "baseline_required"

    deadline = time.monotonic() + 5.0
    sample = probe()
    while sample["host_cpu_percent"] is None and time.monotonic() < deadline:
        sample = probe()

    assert sample["host_cpu_percent"] is not None
    assert 0.0 <= sample["host_cpu_percent"] <= 100.0
    assert "host_cpu" not in sample["reasons"]


def _drm_root(tmp_path: pathlib.Path, cards: dict[str, dict[str, str]]) -> pathlib.Path:
    """Build a real sysfs-shaped DRM tree: ``card<N>/device/<metric>`` files."""
    root = tmp_path / "drm"
    for card, metrics in cards.items():
        device = root / card / "device"
        device.mkdir(parents=True)
        for name, value in metrics.items():
            (device / name).write_text(value, encoding="utf-8")
    return root


def _sysfs_sample(monkeypatch, tmp_path: pathlib.Path, root: pathlib.Path) -> dict:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    probe = ResourceProbe(sysfs_drm_root=root)
    assert probe._nvidia is None
    return probe()


@pytest.mark.skipif(sys.platform != "linux", reason="the sysfs aggregate is Linux-only")
def test_sysfs_metrics_are_averaged_across_cards_and_summed_in_bytes(monkeypatch, tmp_path):
    root = _drm_root(
        tmp_path,
        {
            "card0": {"gpu_busy_percent": "30\n", "mem_info_vram_used": "1048576\n"},
            "card1": {"gpu_busy_percent": "10\n", "mem_info_vram_used": "2097152\n"},
            "cardX": {"gpu_busy_percent": "99\n", "mem_info_vram_used": "99\n"},
        },
    )

    sample = _sysfs_sample(monkeypatch, tmp_path, root)

    # "cardX" is not a card index and is not globbed in.
    assert sample["gpu_utilization_percent"] == pytest.approx(20.0)
    assert sample["gpu_memory_used_bytes"] == 3145728
    assert "gpu" not in sample["reasons"]


@pytest.mark.skipif(sys.platform != "linux", reason="the sysfs aggregate is Linux-only")
@pytest.mark.parametrize(
    "cards",
    [
        {},
        {"card0": {}},
        {"card0": {"gpu_busy_percent": "not a number", "mem_info_vram_used": "1048576"}},
        # A card that reports utilization but no memory would otherwise make an
        # aggregate out of unequal sets of devices.
        {"card0": {"gpu_busy_percent": "30"}},
    ],
)
def test_sysfs_metrics_that_do_not_add_up_report_nothing(monkeypatch, tmp_path, cards):
    sample = _sysfs_sample(monkeypatch, tmp_path, _drm_root(tmp_path, cards))

    assert sample["gpu_utilization_percent"] is None
    assert sample["gpu_memory_used_bytes"] is None
    assert sample["reasons"]["gpu"] == "native_gpu_probe_unavailable"
    # The rest of the sample is unaffected by an absent GPU.
    assert sample["host_memory_total_bytes"] > 0
