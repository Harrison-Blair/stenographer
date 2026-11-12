# SPDX-License-Identifier: GPL-3.0-or-later
"""Session assembly is fail-open and never collects what the user disabled."""

from __future__ import annotations

import dataclasses
import time
from importlib.metadata import version

from stenographer.lib.analytics.store import Store
from stenographer.lib.config.models import Config
from stenographer.lib.diagnostics.session import create_session
from tests.lib.diagnostics.support import AnalyticsHost as _Host


def _configured(*, enabled: bool = True) -> Config:
    defaults = Config.defaults()
    return dataclasses.replace(
        defaults, analytics=dataclasses.replace(defaults.analytics, enabled=enabled)
    )


def test_disabled_analytics_never_opens_a_database(tmp_path):
    collection = create_session(_configured(enabled=False), _Host(tmp_path))
    try:
        identity = collection.start(1)
        collection.checkpoint(identity, "secured_capture", {"capture_s": 1.0})
    finally:
        collection.close()

    assert identity is None
    assert list(tmp_path.iterdir()) == []


def test_an_enabled_session_records_the_host_context_it_was_given(tmp_path):
    collection = create_session(_configured(), _Host(tmp_path), pids=lambda: (4242,))
    try:
        identity = collection.start(1)
        collection.finish(identity, "success", {"recognized_words": 4})
    finally:
        assert collection.close()

    (record,) = Store(tmp_path / "analytics.sqlite3").records()
    assert record["outcome"] == "success"
    assert record["metrics"]["recognized_words"] == 4
    assert record["context"]["os"] == "test"
    assert record["context"]["architecture"] == "test64"
    assert record["context"]["cpu_threads"] == 2
    assert record["context"]["runtime_version"] == version("sherpa-onnx")


def test_an_enabled_session_samples_resources(tmp_path):
    """Resource profiling follows Usage history; it has no setting of its own."""
    host = _Host(tmp_path, resident_bytes=4096)
    collection = create_session(_configured(), host, pids=lambda: (4242,))
    try:
        identity = collection.start(1)
        deadline = time.monotonic() + 5.0
        while not host.probed and time.monotonic() < deadline:
            time.sleep(0.01)
        collection.finish(identity, "success")
    finally:
        assert collection.close()

    assert (4242,) in host.probed
    (record,) = Store(tmp_path / "analytics.sqlite3").records()
    assert record["metrics"]["resource_samples"] >= 1
    assert record["metrics"]["app_rss_bytes_max"] == 4096


def test_a_host_that_cannot_describe_itself_degrades_instead_of_failing(tmp_path):
    collection = create_session(_configured(), _Host(tmp_path, broken=True))
    try:
        identity = collection.start(1)
        collection.checkpoint(identity, "secured_capture", {"capture_s": 1.0})
        collection.finish(identity, "error")
    finally:
        collection.close()

    assert not (tmp_path / "analytics.sqlite3").exists()
