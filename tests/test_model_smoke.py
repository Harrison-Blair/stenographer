# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration smoke for Hugging Face-owned cache resolution."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration

if os.environ.get("STENOGRAPHER_INTEGRATION") != "1":
    pytest.skip("integration suite requires STENOGRAPHER_INTEGRATION=1", allow_module_level=True)


def test_model_probe_honors_huggingface_hub_cache(tmp_path):
    model_id = "stenographer/cache-probe"
    revision = "0123456789abcdef"
    repo = tmp_path / "models--stenographer--cache-probe"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text(revision, encoding="ascii")
    config = repo / "snapshots" / revision / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}", encoding="ascii")

    env = os.environ.copy()
    env.pop("HF_HUB_CACHE", None)
    env["HUGGINGFACE_HUB_CACHE"] = str(tmp_path)
    code = (
        "from stenographer.model import is_model_cached\n"
        f"raise SystemExit(0 if is_model_cached({model_id!r}) else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True)
