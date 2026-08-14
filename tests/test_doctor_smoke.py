# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke for `doctor`: real probe, real exit code, nothing mocked.

Runs the actual capability probe against this machine and asserts the CLI
exit code agrees with the probe's own decision — 0 when everything required
is present, 78 otherwise (spec §8 M6 Verify; exit-78 contract).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from stenographer import doctor  # noqa: E402
from stenographer.cli import main  # noqa: E402
from stenographer.config import Config  # noqa: E402


def test_probe_returns_real_capabilities():
    caps = doctor.probe(Config.defaults())
    assert isinstance(caps, doctor.Capabilities)
    assert caps.audio_player in ("pw-play", "paplay", None)


def test_doctor_exit_code_matches_probe(capsys):
    caps = doctor.probe(Config.defaults())
    expected = 78 if doctor.missing_required(caps) else 0
    assert main(["doctor"]) == expected
    out = capsys.readouterr().out
    assert "capabilities" in out
