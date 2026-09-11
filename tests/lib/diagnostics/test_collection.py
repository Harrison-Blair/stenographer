# SPDX-License-Identifier: GPL-3.0-or-later
"""Privacy boundary and actual fail-open collection, without native-device doubles."""

from dataclasses import replace

from stenographer.lib.analytics.store import Store
from stenographer.lib.config.models import Config
from stenographer.lib.diagnostics.collection import Collection
from stenographer.lib.diagnostics.context import technical_context


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


def test_bad_checkpoint_cannot_prevent_terminal_persistence(
    tmp_path, analytics_session, drain_analytics
):
    path = tmp_path / "analytics.sqlite3"
    collection = Collection(enabled=True, session=analytics_session(path))
    identity = collection.start(1)
    collection.checkpoint(identity, "secured_capture", {"transcript": "must not persist"})
    collection.finish(identity, "cancelled", {"capture_s": 0.5})
    drain_analytics(collection)
    assert collection.health["degraded"]
    assert collection.health["dropped_checkpoints"] == 1
    (record,) = Store(path).records()
    assert record["outcome"] == "cancelled"
    assert record["metrics"] == {"capture_s": 0.5}
    assert "must not persist" not in Store(path).export_json()


def test_a_collection_without_a_session_stays_silent_and_enabled():
    # Session construction failed, but dictation keeps running: every call is
    # accepted and answers with "nothing collected".
    collection = Collection(enabled=True, failures=1)

    assert collection.start(1) is None
    collection.checkpoint(None, "secured_capture", {"capture_s": 1.0})
    collection.finish(None, "success")
    assert collection.close() is None

    assert collection.health == {
        "enabled": True,
        "degraded": True,
        "dropped_checkpoints": 1,
    }


def test_a_failing_session_is_counted_once_per_rejected_call():
    class _Refusing:
        @property
        def health(self):
            return {"degraded": False, "dropped_checkpoints": 0}

        def start(self, utterance_id, **kwargs):
            raise RuntimeError("session gone")

        def checkpoint(self, identity, phase, metrics=None, **kwargs):
            raise RuntimeError("session gone")

        def finish(self, identity, outcome, metrics=None):
            raise RuntimeError("session gone")

        def close(self, timeout=2.0):
            raise RuntimeError("session gone")

    collection = Collection(enabled=True, session=_Refusing())

    assert collection.start(1) is None
    collection.checkpoint("run:1", "secured_capture")
    collection.finish("run:1", "success")
    assert collection.close() is None

    assert collection.health["dropped_checkpoints"] == 4
    assert collection.health["degraded"] is True
