# SPDX-License-Identifier: GPL-3.0-or-later
"""Real temporary endpoints: authentication, framing and disconnect ownership."""

import json
import os
import socket
import threading

import pytest

from stenographer.platform.local_control import LocalControlTransport


def test_real_transport_authentication_and_disconnect(tmp_path):
    transport = LocalControlTransport(tmp_path / "control")
    sessions = []
    disconnected = threading.Event()

    def handle(message, owner):
        sessions.append(owner)
        return {"id": message["id"]}

    server = transport.serve(handle, lambda owner: disconnected.set())
    client = transport.connect()
    try:
        assert client.request({"id": 1}) == {"id": 1}
        assert client.request({"id": 2}) == {"id": 2}
        assert sessions[0] == sessions[1]
        endpoint = json.loads((tmp_path / "control/endpoint.json").read_text())
        with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as stranger:
            stranger.sendall(b'{"token":"wrong","message":{"id":3}}\n')
            assert stranger.recv(1024) == b""
        assert len(sessions) == 2
        if os.name != "nt":
            assert (tmp_path / "control").stat().st_mode & 0o777 == 0o700
            assert (tmp_path / "control/endpoint.json").stat().st_mode & 0o777 == 0o600
        disconnected.clear()
        client.close()
        assert disconnected.wait(2)
    finally:
        client.close()
        server.close()
    assert not (tmp_path / "control/endpoint.json").exists()


def test_live_endpoint_is_not_overwritten_and_large_frames_rejected(tmp_path):
    transport = LocalControlTransport(tmp_path / "control")
    server = transport.serve(lambda message, owner: message, lambda owner: None)
    try:
        with pytest.raises(OSError, match="already running"):
            transport.serve(lambda message, owner: message, lambda owner: None)
        client = transport.connect()
        try:
            with pytest.raises(ValueError, match="too large"):
                client.request({"value": "x" * 20000})
            assert client.request({"value": 1}) == {"value": 1}
        finally:
            client.close()
    finally:
        server.close()
