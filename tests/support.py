# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test utilities."""

import time


def wait_until(predicate, timeout, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
