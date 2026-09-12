# SPDX-License-Identifier: GPL-3.0-or-later
"""The integration smoke suite is opt-in and never collected without the flag.

`*_smoke.py` modules import at module scope what they exercise for real (evdev,
uinput, pty/termios, the ASR model, Xlib). Skipping has to happen at collection
time so those imports never run in the unit suite; a marker-based skip would
already have imported the module.

The unit suite is also fenced off from the user's own directories and from the
network: see :func:`_isolate_host_directories` and
:func:`_block_outbound_connections`.
"""

from __future__ import annotations

import os
import pathlib
import socket
import threading

import pytest

#: Every environment variable the host providers consult when they resolve the
#: configuration file, the state directory, or the runtime directory --- see
#: ``lib/platform/linux/dirs.py`` and the macOS and Windows providers. All of
#: them take precedence over the home directory, so redirecting them is enough
#: to move every resolved path without touching ``HOME``. ``XDG_CACHE_HOME`` is
#: not read by this project but is honoured by huggingface_hub.
_HOST_DIRECTORY_VARS = (
    "XDG_CONFIG_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "APPDATA",
    "LOCALAPPDATA",
)


@pytest.fixture(autouse=True)
def _isolate_host_directories(request, monkeypatch, tmp_path_factory):
    """Point every host directory at a fresh temporary tree for unit tests.

    A unit test that reaches a real code path — ``stenographer transcribe``
    opening an analytics session, ``doctor`` naming a log, anything resolving
    the configuration path — otherwise writes into the user's own
    ``~/.local/state/stenographer`` and ``~/.config/stenographer``. That
    happened: file-sourced analytics rows from suite runs accumulated in the
    real database. Tests marked ``integration`` are exempt, because using the
    real host state is exactly what they are for.
    """

    if request.node.get_closest_marker("integration") is not None:
        return
    base = tmp_path_factory.mktemp("host")
    for name in _HOST_DIRECTORY_VARS:
        monkeypatch.setenv(name, str(base / name.casefold()))
    # An inherited override would defeat every redirect above.
    monkeypatch.delenv("STENOGRAPHER_CONFIG", raising=False)


#: The address families a unit test must never dial. Everything else is left
#: alone on purpose: ``AF_UNIX`` carries Wayland, X11, PulseAudio/PipeWire and
#: journald, and blocking it would break the overlay and platform suites.
_NETWORK_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})

#: The real callables, captured before any test can replace them.
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_CREATE_CONNECTION = socket.create_connection
_REAL_SOCKETPAIR = socket.socketpair

#: Set while :func:`_socketpair` is running. CPython has no ``AF_UNIX`` on
#: Windows, so ``socket.socketpair`` there is emulated by connecting a real
#: ``AF_INET`` socket to a freshly bound loopback listener — an outbound
#: connection by every measure this guard can take. The permit is thread-local
#: and depth-counted because the emulation connects on the calling thread,
#: inside the wrapper, so no other thread's connect can slip through it.
_SOCKETPAIR_PERMIT = threading.local()


def _permitted() -> bool:
    return getattr(_SOCKETPAIR_PERMIT, "depth", 0) > 0


def _describe(address: object) -> str:
    """``host:port`` for the tuples both INET families use. PURE."""

    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return repr(address)


def _refuse(address: object) -> None:
    pytest.fail(
        f"a unit test tried to connect to {_describe(address)}. "
        "The unit suite is offline: it must not depend on a server, a model "
        "host or the internet being there. Stub the client. Marking the test "
        "`integration` is the other answer, but it costs more than it looks: "
        "an integration test also gives up the host-directory isolation in "
        "`tests/conftest.py`, "
        "CI never runs it (`-m 'not integration'`), and a bare local `pytest` "
        "does run it with both fences down."
    )


def _connect(self, address, *args, **kwargs):
    if self.family in _NETWORK_FAMILIES and not _permitted():
        _refuse(address)
    return _REAL_CONNECT(self, address, *args, **kwargs)


def _connect_ex(self, address, *args, **kwargs):
    if self.family in _NETWORK_FAMILIES and not _permitted():
        _refuse(address)
    return _REAL_CONNECT_EX(self, address, *args, **kwargs)


def _create_connection(address, *args, **kwargs):
    # Always an INET connection by definition, and guarded here as well as at
    # ``connect`` so the failure names the address the caller asked for rather
    # than whichever resolved address was dialled first.
    if not _permitted():
        _refuse(address)
    return _REAL_CREATE_CONNECTION(address, *args, **kwargs)


def _socketpair(*args, **kwargs):
    depth = getattr(_SOCKETPAIR_PERMIT, "depth", 0)
    _SOCKETPAIR_PERMIT.depth = depth + 1
    try:
        return _REAL_SOCKETPAIR(*args, **kwargs)
    finally:
        _SOCKETPAIR_PERMIT.depth = depth


@pytest.fixture(autouse=True)
def _block_outbound_connections(request, monkeypatch):
    """Turn any outbound TCP connection from a unit test into a failure.

    A default ``Config`` now enables the Ollama-backed refine stage, so objects
    built from ``Config.defaults()`` began quietly POSTing to a real server on
    the developer's own machine; the transport error that came back was
    swallowed and nothing said a word. The guard sits at the socket layer
    rather than at ``urlopen`` so that it is proxy-proof — with ``http_proxy``
    set, one of those "loopback" requests left the machine entirely — and so
    that it catches anything bypassing urllib.

    ``pytest.fail`` raises a ``BaseException``, which matters: the code paths
    this catches are wrapped in ``except Exception`` handlers that would
    otherwise absorb it. Tests marked ``integration`` are exempt, because
    reaching a real host is exactly what they are for. ``socket.getaddrinfo``
    is left alone — resolving a name is not connecting to it, and blocking it
    reports the wrong problem.
    """

    if request.node.get_closest_marker("integration") is not None:
        return
    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "create_connection", _create_connection)
    monkeypatch.setattr(socket, "socketpair", _socketpair)


@pytest.fixture
def drain_analytics():
    def drain(session):
        # Verify persistence independently of the daemon's two-second shutdown
        # budget, allowing for slow CI disks while retaining a bounded failure.
        assert session.close(timeout=15), session.health

    return drain


@pytest.fixture
def analytics_session(request, drain_analytics):
    from stenographer.lib.analytics.session import AnalyticsSession

    def create(path, **kwargs):
        session = AnalyticsSession(path, **kwargs)
        request.addfinalizer(lambda: drain_analytics(session))
        return session

    return create


def pytest_ignore_collect(collection_path: pathlib.Path) -> bool | None:
    if collection_path.name.endswith("_smoke.py"):
        return os.environ.get("STENOGRAPHER_INTEGRATION") != "1"
    return None
