# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests resolve the stenographer data dir inside the test's temporary tree."""

from __future__ import annotations

import os
from pathlib import Path

from stenographer.lib.platform import current_platform


def test_the_data_dir_resolves_under_the_test_temporary_tree(tmp_path_factory):
    data_dir = current_platform().data_dir(os.environ, Path.home())
    assert data_dir.is_relative_to(tmp_path_factory.getbasetemp())
