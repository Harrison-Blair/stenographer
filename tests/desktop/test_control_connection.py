# SPDX-License-Identifier: GPL-3.0-or-later
"""Real temporary control sessions survive a desktop process crash safely."""

import os
import subprocess
import sys
import threading

import pytest

from stenographer.control import ControlClient, Maintenance
from stenographer.platform.local_control import LocalControlTransport
from stenographer_desktop.services import DesktopServices


class EndpointHost:
    def __init__(self, transport):
        self.transport = transport

    def control_transport(self):
        return self.transport


def test_desktop_process_crash_releases_real_maintenance_lease(tmp_path):
    pytest.importorskip("PySide6")
    transport = LocalControlTransport(tmp_path / "control")
    maintenance = Maintenance()
    acquired = threading.Event()
    released = threading.Event()

    def handle(message, owner):
        ok = maintenance.begin(owner, message["payload"]["kind"], busy=False)
        if ok:
            acquired.set()
        return {"version": 1, "id": message["id"], "ok": ok}

    def disconnected(owner):
        if maintenance.release(owner):
            released.set()

    server = transport.serve(handle, disconnected)
    script = """
import os
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from stenographer.control import ControlClient
from stenographer.platform.local_control import LocalControlTransport
from stenographer_desktop.services import DesktopServices
class Host:
    def control_transport(self):
        return LocalControlTransport(Path(sys.argv[1]))
app = QApplication([])
services = DesktopServices(Path(sys.argv[1]) / 'config.toml')
services._client = ControlClient(Host())
with services.maintenance('shortcut'):
    os._exit(17)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "control")],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 17, result.stderr
        assert acquired.is_set()
        assert released.wait(2)
        assert not maintenance.occupied
        assert maintenance.begin("another-session", "sound", busy=False)
    finally:
        server.close()


def test_stale_control_response_is_rejected_without_local_setup_fallback(tmp_path):
    transport = LocalControlTransport(tmp_path / "control")
    server = transport.serve(
        lambda message, owner: {"version": 1, "id": "stale", "ok": True},
        lambda owner: None,
    )
    services = DesktopServices(tmp_path / "config.toml")
    services._client = ControlClient(EndpointHost(transport))
    try:
        with pytest.raises(ValueError, match="stale"), services.maintenance("calibration"):
            pytest.fail("Malformed daemon responses must not admit local microphone capture")
    finally:
        services.close()
        server.close()


def test_failed_heartbeat_cancels_capture_wait_and_reconnect_never_revives_lease(tmp_path):
    from stenographer.calibration import CalibrationCancelledError, wait_for_capture

    transport = LocalControlTransport(tmp_path / "control")
    heartbeat_bad = threading.Event()
    requests = []

    def handle(message, owner):
        requests.append((message["action"], owner))
        response = {
            "version": 1,
            "id": message["id"],
            "ok": True,
            "status": {"lifecycle": "maintenance"},
        }
        if message["action"] == "status" and heartbeat_bad.is_set():
            response["id"] = "expired-response"
        return response

    server = transport.serve(handle, lambda owner: None)
    services = DesktopServices(tmp_path / "config.toml")
    services.platform = EndpointHost(transport)
    services._client = ControlClient(services.platform)
    ended = threading.Event()
    try:
        with services.maintenance("calibration") as cancellation:

            def wait():
                try:
                    wait_for_capture(30, cancellation)
                except CalibrationCancelledError:
                    ended.set()

            worker = threading.Thread(target=wait, daemon=True)
            worker.start()
            heartbeat_bad.set()
            with pytest.raises(ValueError, match="stale"):
                services.status()
            assert cancellation.is_set()
            assert ended.wait(0.5)
            worker.join(timeout=1)
            heartbeat_bad.clear()
            assert services.status()["ok"]
            assert cancellation.is_set()
        assert not any(action == "maintenance_end" for action, _ in requests)
        assert requests[0][1] != requests[-1][1]
    finally:
        services.close()
        server.close()


def test_explicit_desktop_close_cancels_active_maintenance(tmp_path):
    transport = LocalControlTransport(tmp_path / "control")
    server = transport.serve(
        lambda message, owner: {"version": 1, "id": message["id"], "ok": True},
        lambda owner: None,
    )
    services = DesktopServices(tmp_path / "config.toml")
    services._client = ControlClient(EndpointHost(transport))
    try:
        with services.maintenance("shortcut") as cancellation:
            assert not cancellation.is_set()
            services.close()
            assert cancellation.is_set()
    finally:
        services.close()
        server.close()
