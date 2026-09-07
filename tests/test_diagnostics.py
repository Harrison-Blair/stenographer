# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy boundary and actual fail-open collection, without native-device doubles."""

from dataclasses import replace

from stenographer.analytics import AnalyticsSession, Store
from stenographer.config import Config
from stenographer.diagnostics import Collection, technical_context


def test_technical_context_never_retains_user_paths_or_prompt():
    cfg = Config.defaults()
    cfg = replace(
        cfg,
        asr=replace(
            cfg.asr,
            model="/private/model",
            hotwords="private words",
            initial_prompt="secret prompt",
        ),
        audio=replace(cfg.audio, input_device="C:\\private\\device"),
    )
    context = technical_context(cfg)
    assert context["model"] == "local_model"
    assert context["device"] == "configured_device"
    assert "private" not in str(context)
    assert "secret" not in str(context)


def test_bad_checkpoint_cannot_prevent_terminal_persistence(tmp_path):
    path = tmp_path / "analytics.sqlite3"
    collection = Collection(enabled=True, session=AnalyticsSession(path))
    identity = collection.start(1)
    collection.checkpoint(identity, "secured_capture", {"transcript": "must not persist"})
    collection.finish(identity, "cancelled", {"capture_s": 0.5})
    assert collection.close()
    assert collection.health["degraded"]
    assert collection.health["dropped_checkpoints"] == 1
    (record,) = Store(path).records()
    assert record["outcome"] == "cancelled"
    assert record["metrics"] == {"capture_s": 0.5}
    assert "must not persist" not in Store(path).export_json()
