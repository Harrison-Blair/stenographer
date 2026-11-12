# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux CPU topology parsing against a real (temporary) sysfs-shaped tree."""

from __future__ import annotations

import pytest

from stenographer.lib.platform.linux.cpu import count_physical_cores, physical_core_count


def _make_topology(root, cpu_to_core, package="0"):
    """Build a fake /sys topology tree mapping cpu index -> core_id."""
    for cpu, core in cpu_to_core.items():
        topo = root / f"cpu{cpu}" / "topology"
        topo.mkdir(parents=True)
        (topo / "physical_package_id").write_text(package, encoding="ascii")
        (topo / "core_id").write_text(str(core), encoding="ascii")


@pytest.mark.parametrize(
    ("cpu_to_core", "affinity", "expected"),
    [
        pytest.param({0: 0, 1: 1, 2: 2, 3: 3}, {0, 1, 2, 3}, 4, id="distinct"),
        pytest.param({0: 0, 1: 0, 2: 1, 3: 1}, {0, 1, 2, 3}, 2, id="siblings"),
        pytest.param({0: 0, 1: 1, 2: 2, 3: 3}, {0, 1}, 2, id="affinity"),
        pytest.param({i: i for i in range(16)}, set(range(16)), 16, id="uncapped"),
        pytest.param({}, {0, 1}, None, id="unreadable"),
        pytest.param({0: 0}, {0, 1}, None, id="partial"),
    ],
)
def test_counts_topology(tmp_path, cpu_to_core, affinity, expected):
    _make_topology(tmp_path, cpu_to_core)
    assert count_physical_cores(affinity, tmp_path) == expected


def test_same_core_id_in_two_packages_counts_twice(tmp_path):
    # core_id restarts per socket, so the package half of the pair is load-bearing.
    _make_topology(tmp_path, {0: 0, 1: 1}, package="0")
    _make_topology(tmp_path, {2: 0, 3: 1}, package="1")
    assert count_physical_cores({0, 1, 2, 3}, tmp_path) == 4


def test_live_probe_reports_a_positive_count_or_none():
    count = physical_core_count()
    assert count is None or count >= 1


def _write_proc(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def test_process_cpu_ticks_add_user_and_system_after_the_command_name(tmp_path):
    from stenographer.lib.platform.linux.cpu import read_process_cpu_ticks

    # A command name with spaces and a closing parenthesis must not shift fields.
    fields = ["S", "1", "2", "3", "0", "-1", "4194560", "10", "0", "0", "0", "70", "30"]
    _write_proc(tmp_path, "42/stat", f"42 (py thon) x) {' '.join(fields)} 0 0 20 0\n")

    assert read_process_cpu_ticks(42, tmp_path) == 100
    assert read_process_cpu_ticks(43, tmp_path) is None


def test_process_resident_bytes_use_statm_pages(tmp_path):
    from stenographer.lib.platform.linux.cpu import read_process_resident_bytes

    _write_proc(tmp_path, "42/statm", "5000 300 100 10 0 200 0\n")

    assert read_process_resident_bytes(42, tmp_path, page_size=4096) == 300 * 4096
    assert read_process_resident_bytes(43, tmp_path, page_size=4096) is None


def test_linux_platform_cpu_counters_read_this_process_from_proc():
    import os

    from stenographer.lib.platform.linux.provider import LinuxPlatform

    counters = LinuxPlatform().process_counters()

    assert counters.process_cpu_ticks(os.getpid()) >= 0
    assert counters.process_resident_bytes(os.getpid()) > 0
    assert counters.clock_ticks > 0
