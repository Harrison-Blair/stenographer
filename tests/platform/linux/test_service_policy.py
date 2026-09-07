# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure service ownership admission; no mocked native service operations."""

from stenographer.platform.linux.service import restart_targets_process


def test_restart_requires_the_actual_active_service_process():
    properties = {"LoadState": "loaded", "ActiveState": "active", "MainPID": "42"}
    assert restart_targets_process(properties, 42)
    assert not restart_targets_process(properties, 99)
    assert not restart_targets_process({**properties, "MainPID": "0"}, 42)
    assert not restart_targets_process({**properties, "ActiveState": "inactive"}, 42)
    assert not restart_targets_process({**properties, "LoadState": "not-found"}, 42)
    assert not restart_targets_process({}, 42)
