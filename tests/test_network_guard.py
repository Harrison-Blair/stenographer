# SPDX-License-Identifier: GPL-3.0-or-later
"""The network guard in :mod:`tests.conftest` guarding itself.

The guard is insurance: the suite makes no outbound connection today, so
nothing else in 2000-odd tests would notice if it stopped working. Emptying
:func:`~tests.conftest._refuse`, widening the family check, or capturing an
already-patched callable into one of the ``_REAL_*`` globals would each leave
the suite green and the protection gone. These tests are what notices.

The refusal message is asserted on deliberately: it is the guard's entire
interface to the contributor who trips it, and a message that fails to name
the address it refused would be nearly useless.
"""

from __future__ import annotations

import contextlib
import socket
import urllib.request

import pytest

from tests import conftest


def test_an_outbound_connection_is_refused_by_address():
    """The guard fires, and the failure names where the test was headed."""

    with (
        pytest.raises(pytest.fail.Exception) as refusal,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
    ):
        sock.connect(("127.0.0.1", 11434))
    assert "127.0.0.1:11434" in str(refusal.value)
    assert "offline" in str(refusal.value)


def test_a_connect_ex_probe_is_refused():
    """``connect_ex`` is a connection primitive with no backstop.

    ``create_connection`` still funnels into the patched ``connect`` if its own
    patch is dropped, so only the address in the message is lost. Drop this
    one and a port scan runs for real with every other test still green.
    """

    with (
        pytest.raises(pytest.fail.Exception) as refusal,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
    ):
        sock.connect_ex(("127.0.0.1", 11434))
    assert "127.0.0.1:11434" in str(refusal.value)


def test_a_urllib_request_is_refused():
    """The whole reason the guard sits at the socket layer.

    ``urllib`` never calls ``socket.socket.connect`` itself — ``http.client``
    reaches the network through ``socket.create_connection`` — so this is the
    patch that actually fires for every request the refine client makes.
    """

    with pytest.raises(pytest.fail.Exception) as refusal:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
    assert "127.0.0.1:11434" in str(refusal.value)


def test_a_proxied_request_is_refused_by_its_real_destination():
    """A "loopback" request under a proxy leaves the machine, and is named.

    This is the case a guard at ``urlopen`` could not see: the URL says
    ``127.0.0.1`` while the connection goes to the proxy. The message has to
    name where the bytes were actually headed, or it misleads. The opener is
    built explicitly rather than through ``http_proxy`` so the assertion does
    not depend on when urllib last cached its global opener, and the host is
    under the reserved ``.invalid`` TLD so that a guard which somehow fails to
    fire still reaches nothing real.

    That unresolvable host also demonstrates how early the refusal happens:
    this test passes, so the guard refused before the real
    ``create_connection`` ran and ``proxy.invalid`` was never looked up. A
    refused test emits not even a DNS query. Break the ``create_connection``
    patch and this same test dies in ``getaddrinfo`` instead — which is the
    evidence that, intact, it never gets that far.
    """

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": "http://proxy.invalid:3128"})
    )
    with pytest.raises(pytest.fail.Exception) as refusal:
        opener.open("http://127.0.0.1:11434/api/tags", timeout=1)
    assert "proxy.invalid:3128" in str(refusal.value)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX on this platform")
def test_a_unix_socket_still_connects(tmp_path):
    """Wayland, X11, PipeWire and journald all ride on this."""

    address = str(tmp_path / "socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(address)
        server.listen()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(address)
            accepted, _ = server.accept()
            with accepted:
                client.sendall(b"ok")
                assert accepted.recv(2) == b"ok"


def test_a_socket_pair_still_connects():
    """On Windows this is an ``AF_INET`` connect to a loopback listener."""

    first, second = socket.socketpair()
    with first, second:
        first.sendall(b"ok")
        assert second.recv(2) == b"ok"


def test_the_permit_is_live_while_a_pair_is_being_made(monkeypatch):
    """The permit itself, tested as a property rather than as a platform.

    On Linux ``socket.socketpair`` is the C ``AF_UNIX`` call and never
    connects, so the test above it passes whether or not the permit is granted
    — it is a canary only on Windows, where a pair really is two TCP sockets.
    This test closes that blind spot everywhere by observing the permit
    directly: an ``AF_INET`` connect attempted from inside the wrapper must get
    through the guard. Whether the discard port answers is irrelevant, and
    refused is the normal answer; being *refused by the guard* is the failure,
    and it cannot be swallowed here because ``Failed`` is not an ``OSError``.
    """

    real = conftest._REAL_SOCKETPAIR
    reached = []

    def watching(*args, **kwargs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.05)
            with contextlib.suppress(OSError):
                probe.connect(("127.0.0.1", 9))
            reached.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(conftest, "_REAL_SOCKETPAIR", watching)
    first, second = socket.socketpair()
    with first, second:
        pass
    assert reached == [True]


@pytest.mark.skipif(
    not hasattr(socket, "_fallback_socketpair"),
    reason="CPython only exposes the emulation under this name from 3.13 on",
)
def test_the_windows_socket_pair_emulation_still_connects(monkeypatch):
    """Run the code Windows runs, on whichever platform is running this.

    ``socket.socketpair`` on Windows *is* ``_fallback_socketpair``: no
    ``AF_UNIX`` exists there, so a pair is two real TCP sockets on loopback.
    Every other test here would pass on Linux with the permit removed and fail
    only on Windows CI, which is a bad place to find out.
    """

    monkeypatch.setattr(conftest, "_REAL_SOCKETPAIR", socket._fallback_socketpair)
    first, second = socket.socketpair(socket.AF_INET)
    with first, second:
        first.sendall(b"ok")
        assert second.recv(2) == b"ok"
