# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux CPU topology parsing against a real (temporary) sysfs-shaped tree."""

from __future__ import annotations

from stenographer.platform.linux.cpu import count_physical_cores, physical_core_count


def _make_topology(root, cpu_to_core, package="0"):
    """Build a fake /sys topology tree mapping cpu index -> core_id."""
    for cpu, core in cpu_to_core.items():
        topo = root / f"cpu{cpu}" / "topology"
        topo.mkdir(parents=True)
        (topo / "physical_package_id").write_text(package, encoding="ascii")
        (topo / "core_id").write_text(str(core), encoding="ascii")


def test_counts_one_core_per_distinct_core_id(tmp_path):
    # 4 cpus mapping onto 4 distinct core ids -> 4 physical cores.
    _make_topology(tmp_path, {0: 0, 1: 1, 2: 2, 3: 3})
    assert count_physical_cores({0, 1, 2, 3}, tmp_path) == 4


def test_dedupes_hyperthread_siblings(tmp_path):
    # 4 cpus but only 2 distinct core ids (hyperthread siblings) -> 2.
    _make_topology(tmp_path, {0: 0, 1: 0, 2: 1, 3: 1})
    assert count_physical_cores({0, 1, 2, 3}, tmp_path) == 2


def test_same_core_id_in_two_packages_counts_twice(tmp_path):
    # core_id restarts per socket, so the package half of the pair is load-bearing.
    _make_topology(tmp_path, {0: 0, 1: 1}, package="0")
    _make_topology(tmp_path, {2: 0, 3: 1}, package="1")
    assert count_physical_cores({0, 1, 2, 3}, tmp_path) == 4


def test_counts_only_affinity_visible_cpus(tmp_path):
    # A cgroup/taskset-restricted process must not count cores it cannot use.
    _make_topology(tmp_path, {0: 0, 1: 1, 2: 2, 3: 3})
    assert count_physical_cores({0, 1}, tmp_path) == 2


def test_uncapped_count_is_returned(tmp_path):
    # The eight-thread cap is the core's policy, not the host's report.
    _make_topology(tmp_path, {i: i for i in range(16)})
    assert count_physical_cores(set(range(16)), tmp_path) == 16


def test_empty_affinity_is_unknown(tmp_path):
    assert count_physical_cores(set(), tmp_path) is None


def test_unreadable_topology_is_unknown(tmp_path):
    # No files created under tmp_path -> read_text raises FileNotFoundError (OSError).
    assert count_physical_cores({0, 1}, tmp_path) is None


def test_partial_topology_is_unknown(tmp_path):
    # A half-populated tree must not under-report rather than admit ignorance.
    _make_topology(tmp_path, {0: 0})
    assert count_physical_cores({0, 1}, tmp_path) is None


def test_live_probe_reports_a_positive_count_or_none():
    count = physical_core_count()
    assert count is None or count >= 1
