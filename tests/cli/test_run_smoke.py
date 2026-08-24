# SPDX-License-Identifier: GPL-3.0-or-later
"""Real deficient-environment startup gate for ``stenographer run``.

No capability is faked.  The check runs only when the host's doctor reports a
real missing requirement, and holds the real daemon lock to prove capability
failure takes precedence over lock acquisition.  A fully capable host covers
startup through the manual dictation acceptance procedure instead.
"""

from __future__ import annotations

import os

import pytest

from stenographer import daemon
from stenographer.cli import doctor
from stenographer.config import Config
from stenographer.platform.linux import lock

pytestmark = pytest.mark.integration


def test_missing_required_capability_precedes_real_lock(capsys):
    cfg = Config.defaults()
    caps = doctor.probe(cfg)
    missing = doctor.missing_required(caps)
    if not missing:
        pytest.skip("host has every required daemon capability")

    fd = lock.acquire_single_instance_lock()
    if fd < 0:
        pytest.skip(f"another instance already holds {lock.LOCK_PATH}")
    try:
        assert daemon.run(cfg) == 78
    finally:
        os.close(fd)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "stenographer: required capabilities unavailable; run `stenographer doctor`\n"
    )
