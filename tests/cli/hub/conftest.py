# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared hub test fixtures."""

import time

import pytest


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()
