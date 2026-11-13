# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared hub test fixtures."""

import asyncio
import inspect
import threading
import time

import pytest

from stenographer.cli.hub.session_titles import THREAD_NAME
from stenographer.lib.refine import client
from stenographer.lib.refine.errors import RefineTransportError


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def _ollama_has_no_model(monkeypatch):
    """Stub the Ollama client: a saved recording asks it for a model title in the background.

    The model list is empty, so no automatic title is requested; a request fails as an
    unreachable server does. A test that needs a title injects a fake request instead.
    """

    def unreachable(*_args, **_kwargs):
        raise RefineTransportError("ollama could not be reached")

    monkeypatch.setattr(client, "_model_listing", lambda _url: [])
    monkeypatch.setattr(client, "_post_read", unreachable)
    yield
    # A title thread of this test must not reach the real client after the stub ends.
    for thread in threading.enumerate():
        if thread.name == THREAD_NAME:
            thread.join(timeout=10)
            assert not thread.is_alive(), "a title request of the test did not end"


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
    return None
