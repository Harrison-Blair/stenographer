# SPDX-License-Identifier: GPL-3.0-or-later
"""The offline model-cache probe, against a real Hugging Face cache directory.

``is_model_cached`` delegates the cache layout to huggingface_hub, which reads
its cache root once at import time. The probe therefore runs in a real child
interpreter with ``HF_HOME`` pointed at a temporary cache — no network, no
model, and no mutation of this process's environment. ``download_model`` is the
only networked function in the module and is never called here.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

_PROBE = """
import json
from stenographer.lib.transcribe.download import is_model_cached
print(json.dumps([is_model_cached("acme/tiny-en"), is_model_cached("acme/absent")]))
"""


def _write_cached_model(cache_home: pathlib.Path, *, filename: str) -> None:
    """Create the hub layout huggingface_hub resolves a cached file through."""
    repo = cache_home / "hub" / "models--acme--tiny-en"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("abc123", encoding="utf-8")
    snapshot = repo / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / filename).write_text("{}", encoding="utf-8")


def _probe(cache_home: pathlib.Path) -> list[bool]:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env={**os.environ, "HF_HOME": str(cache_home), "HF_HUB_OFFLINE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(completed.stdout)


def test_a_model_with_its_config_in_the_cache_is_reported_cached(tmp_path):
    _write_cached_model(tmp_path, filename="config.json")

    cached, absent = _probe(tmp_path)

    assert cached is True
    # A repository that was never fetched is not cached, and no network call is
    # made to find that out.
    assert absent is False


def test_a_cache_entry_without_config_json_is_not_a_usable_model(tmp_path):
    # The weights alone cannot be loaded locally, so the probe must say no
    # rather than send the daemon into a local-files-only load that fails.
    _write_cached_model(tmp_path, filename="model.bin")

    assert _probe(tmp_path) == [False, False]
