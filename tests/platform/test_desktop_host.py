# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure provider vocabulary and real native resource observations."""

from pathlib import Path

from stenographer.platform import current_platform
from stenographer.platform.base import Platform
from stenographer.platform.macos import MacOSPlatform
from stenographer.platform.windows import WindowsPlatform


def test_macos_paths_and_unavailable_service():
    platform = MacOSPlatform()
    home = Path("home")
    assert (
        platform.config_path({}, home)
        == home / "Library/Application Support/stenographer/config.toml"
    )
    assert platform.state_dir({"XDG_STATE_HOME": "state"}, home) == Path("state/stenographer")
    assert not platform.service_status().available
    assert not platform.service_action("start")[0]
    assert isinstance(platform, Platform)


def test_focused_keys_share_portable_vocabulary():
    platform = WindowsPlatform()
    assert platform.focused_key_name(ord("A")) == "KEY_A"
    assert platform.focused_key_name(0x01000021, 0xA3) == "KEY_RIGHTCTRL"
    assert platform.focused_key_name(0x01000030) == "KEY_F1"
    assert platform.focused_key_name(-1) is None


def test_native_resources_have_real_process_identity():
    platform = current_platform()
    pid, started = platform.process_identity()
    assert platform.process_alive(pid, started) is True
    assert platform.process_alive(pid, started - 10) is False
    probe = platform.resource_probe()
    sample = probe((pid,))
    assert sample["cpu_seconds"] >= 0
    assert sample["resident_bytes"] > 0
    assert sample["host_memory_total_bytes"] > 0
    assert sample["host_cpu_percent"] is None
    if sample["gpu_memory_used_bytes"] is None:
        assert "gpu" in sample["reasons"]
    else:
        assert sample["gpu_memory_used_bytes"] >= 0


def test_retiring_registered_child_does_not_subtract_cpu():
    import subprocess
    import sys

    probe = current_platform().resource_probe()
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; start=time.process_time()\n"
            "while time.process_time()-start < .1: pass\n"
            'print("ready",flush=True); input()',
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        active = probe((child.pid,))
        own = probe()
        assert active["resident_bytes"] > own["resident_bytes"]
        child.communicate("\n", timeout=5)
        retired = probe()
        assert retired["cpu_seconds"] >= active["cpu_seconds"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
