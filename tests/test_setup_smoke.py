# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in real microphone and active-service checks for interactive setup.

These checks are intentionally observational unless their narrower opt-ins are
also set. They never download a model, install a unit, enable one, or start an
inactive unit.
"""

from __future__ import annotations

import io
import os

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)

from stenographer import doctor, setup  # noqa: E402
from stenographer.calibration import calibrate_spectrum_floor  # noqa: E402
from stenographer.config import Config  # noqa: E402


def test_real_microphone_display_floor_calibration():
    if os.environ.get("STENOGRAPHER_CALIBRATION_SMOKE") != "1":
        pytest.skip("set STENOGRAPHER_CALIBRATION_SMOKE=1 and keep the room quiet")

    floor = calibrate_spectrum_floor(
        Config.defaults().audio.input_device, on_countdown=lambda _: None
    )

    assert -96.0 <= floor <= -13.0


def test_restart_policy_uses_real_user_service_status():
    _, active = doctor._service_status()

    assert setup.restart_eligible(
        config_changed=True,
        custom_config=False,
        missing_required=False,
        service_active=active,
    ) is (active == "active")


def test_real_active_service_restart():
    if os.environ.get("STENOGRAPHER_SETUP_RESTART_SMOKE") != "1":
        pytest.skip("set STENOGRAPHER_SETUP_RESTART_SMOKE=1 to restart an active user service")
    if os.environ.get("STENOGRAPHER_CONFIG"):
        pytest.skip("a custom STENOGRAPHER_CONFIG must never trigger service restart")
    caps = doctor.probe(Config.defaults())
    if caps.service_active != "active":
        pytest.skip("stenographer.service is not active; setup must not start it")
    if doctor.missing_required(caps):
        pytest.skip("setup must not restart while a required capability is missing")

    output = io.StringIO()
    console = setup._Console(io.StringIO(), output, output)

    assert setup._restart_service(console) is True
    assert "Restarted stenographer.service" in output.getvalue()
