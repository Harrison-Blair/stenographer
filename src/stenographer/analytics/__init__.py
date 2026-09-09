# SPDX-License-Identifier: GPL-3.0-or-later
"""Numeric analytics collection and reporting services."""

from pathlib import Path

from stenographer.analytics.metrics import count_words, distribution, local_date_bound
from stenographer.analytics.session import AnalyticsSession
from stenographer.analytics.store import Filters, Store

__all__ = [
    "AnalyticsSession",
    "Filters",
    "Store",
    "count_words",
    "database_path",
    "distribution",
    "local_date_bound",
]


def database_path() -> Path:
    # The provider owns all directory/environment semantics.
    import os

    from stenographer.platform import current_platform

    return current_platform().state_dir(os.environ, Path.home()) / "analytics.sqlite3"
