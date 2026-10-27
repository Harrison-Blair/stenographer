# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux CPU topology parsing against a real (temporary) sysfs-shaped tree."""

from __future__ import annotations

from stenographer.lib.platform.linux.cpu import count_physical_cores, physical_core_count


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


def _write_proc(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def test_system_cpu_times_sum_busy_and_idle_jiffies(tmp_path):
    from stenographer.lib.platform.linux.cpu import read_system_cpu_times

    # user nice system idle iowait irq softirq steal guest guest_nice
    _write_proc(tmp_path, "stat", "cpu  100 5 50 800 20 3 2 10 7 1\ncpu0 1 1 1 1 1 1 1 1 1 1\n")

    assert read_system_cpu_times(tmp_path) == (990, 820)


def test_system_cpu_times_unreadable_is_none(tmp_path):
    from stenographer.lib.platform.linux.cpu import read_system_cpu_times

    assert read_system_cpu_times(tmp_path) is None
    _write_proc(tmp_path, "stat", "intr 1 2 3\n")
    assert read_system_cpu_times(tmp_path) is None


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
    total, idle = counters.system_cpu_times()
    assert total >= idle > 0
    assert counters.clock_ticks > 0


def test_null_process_counters_report_no_cpu_or_memory():
    from stenographer.lib.platform.null_process_counters import NullProcessCounters

    counters = NullProcessCounters()

    assert counters.system_cpu_times() is None
    assert counters.process_cpu_ticks(1) is None
    assert counters.process_resident_bytes(1) is None
