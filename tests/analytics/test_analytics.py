# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure arithmetic and real temporary SQLite acceptance for personal analytics."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime

import pytest

from stenographer.analytics import AnalyticsSession, Filters, Store, count_words, distribution
from stenographer.analytics.metrics import clean_context, clean_metrics, local_date_bound, summarize
from stenographer.analytics.resources import ResourceSummary

# Persistence assertions must tolerate slow CI disks independently of the
# daemon's two-second shutdown budget. A timeout still fails with writer health.
_DRAIN_TIMEOUT_SECONDS = 15


def drain(session):
    assert session.close(timeout=_DRAIN_TIMEOUT_SECONDS), session.health


@pytest.fixture
def analytics_session(request):
    def create(path, **kwargs):
        session = AnalyticsSession(path, **kwargs)
        request.addfinalizer(lambda: drain(session))
        return session

    return create


def checkpoint(identity="run:1", revision=0, phase="accepted_start", **metrics):
    return {
        "id": identity,
        "run_id": "run",
        "source": "hotkey",
        "started_at": "2026-01-01T12:00:00.000000+00:00",
        "updated_at": "2026-01-01T12:00:01.000000+00:00",
        "revision": revision,
        "phase": phase,
        "outcome": None,
        "context": {"model": "medium.en", "device": "USB mic"},
        "metrics": metrics,
    }


def test_words_and_percentiles_have_one_definition():
    assert count_words("Hello, don't split a curly\u2019s apostrophe; twenty-one! 123 ___ ...") == 9
    assert distribution([1, 2, 3, None]) == {
        "count": 3,
        "missing": 1,
        "average": 2.0,
        "p95": 3.0,
        "p99": 3.0,
    }
    result = distribution(list(range(1, 101)))
    assert result["p95"] == 95
    assert result["p99"] == 99
    assert distribution([None])["average"] is None


def test_missing_measurements_remain_unknown_and_headlines_survive_failed_delivery():
    accepted = checkpoint(recognized_words=12, asr_audio_s=5.75)
    accepted["outcome"] = "copy_failed"
    empty = checkpoint("run:2", asr_audio_s=3.25, recognized_words=0)
    empty["outcome"] = "empty"
    rejected = checkpoint("run:3", capture_s=2)
    result = summarize([accepted, empty, rejected])
    assert result["totals"]["recognized_words"] == 12
    assert result["totals"]["asr_audio_s"] == 9
    assert result["metrics"]["asr_audio_s"]["count"] == 2
    assert result["metrics"]["asr_audio_s"]["missing"] == 1
    assert result["metrics"]["decode_ms"]["p95"] is None
    assert result["totals"]["incomplete"] == 1


@pytest.mark.parametrize(
    "values",
    [
        {"transcript": "private"},
        {"audio": [1]},
        {"recognized_words": "private"},
        {"capture_s": float("nan")},
        {"capture_s": -1},
    ],
)
def test_metrics_reject_content_and_invalid_numbers(values):
    with pytest.raises(ValueError):
        clean_metrics(values)


def test_context_rejects_private_fields():
    for name in ("transcript", "hotwords", "file_path", "prompt", "serial", "credential"):
        with pytest.raises(ValueError):
            clean_context({name: "private"})
    assert clean_context({"device": "USB mic", "cpu_threads": 4}) == {
        "device": "USB mic",
        "cpu_threads": 4,
    }


def test_local_date_bounds_are_explicit_utc_and_end_is_exclusive():
    start = datetime.fromisoformat(local_date_bound("2026-01-01"))
    end = datetime.fromisoformat(local_date_bound("2026-01-01", end=True))
    assert start.tzinfo == UTC
    assert (end - start).total_seconds() == 86400


def test_checkpoint_revision_deduplication_order_and_terminal_seal(tmp_path):
    store = Store(tmp_path / "analytics.db")
    assert store.write_checkpoint(checkpoint())
    assert store.write_checkpoint(
        checkpoint(revision=2, phase="accepted_recognition", recognized_words=7)
    )
    assert not store.write_checkpoint(checkpoint(revision=1, phase="secured_capture"))
    assert not store.write_checkpoint(
        checkpoint(revision=2, phase="accepted_recognition", recognized_words=99)
    )
    with pytest.raises(ValueError):
        store.write_checkpoint(checkpoint(revision=3, phase="secured_capture"))
    terminal = checkpoint(revision=3, phase="terminal", recognized_words=7)
    terminal["outcome"] = "cancelled"
    assert store.write_checkpoint(terminal)
    assert not store.write_checkpoint(checkpoint(revision=4, phase="terminal", recognized_words=99))
    assert store.report()["totals"]["recognized_words"] == 7
    assert [row["revision"] for row in store.timeline("run:1")] == [0, 2, 3]


def test_delete_suppresses_delayed_starts_and_checkpoints_and_future_work_survives(tmp_path):
    store = Store(tmp_path / "analytics.db")
    store.write_checkpoint(checkpoint(recognized_words=3))
    assert store.preview_delete() == 1
    assert store.delete() == 1
    assert not store.write_checkpoint(checkpoint(revision=3, recognized_words=9))
    assert not store.write_checkpoint(checkpoint("run:queued", recognized_words=10))
    future = checkpoint("run:future", recognized_words=5)
    future["started_at"] = "2999-01-01T00:00:00.000000+00:00"
    assert store.write_checkpoint(future)
    assert store.report()["totals"]["recognized_words"] == 5
    assert store.timeline("run:1") == []


def test_filters_exports_and_file_source_separation(tmp_path):
    store = Store(tmp_path / "analytics.db")
    store.write_checkpoint(checkpoint(recognized_words=3))
    other = checkpoint("run:file", recognized_words=6)
    other["source"] = "file"
    other["context"] = {"model": "small.en", "app_version": "1.0"}
    store.write_checkpoint(other)
    assert store.report()["totals"]["recognized_words"] == 3
    selected = Filters(source=None, model="small.en", app_version="1.0")
    exported = json.loads(store.export_json(selected))
    assert len(exported["records"]) == 1
    assert exported["records"][0]["metrics"]["recognized_words"] == 6
    rows = list(csv.DictReader(io.StringIO(store.export_csv(selected))))
    assert rows[0]["recognized_words"] == "6"
    assert "+00:00" in rows[0]["started_at"]
    assert store.preview_delete(Filters(device="USB mic")) == 1
    assert store.delete(Filters(source="file")) == 1
    assert len(store.records()) == 1


def test_unfinished_work_requires_liveness_evidence_and_survives_reopen(tmp_path):
    path = tmp_path / "analytics.db"
    Store(path).write_checkpoint(checkpoint(recognized_words=7))
    reopened = Store(path)
    assert reopened.records()[0]["outcome"] is None
    assert reopened.mark_interrupted("run", process_confirmed_dead=False) == 0
    assert reopened.mark_interrupted("run", process_confirmed_dead=True) == 1
    assert reopened.records()[0]["outcome"] == "interrupted"
    assert reopened.report()["totals"]["recognized_words"] == 7


def test_unsupported_schema_is_never_overwritten(tmp_path):
    path = tmp_path / "analytics.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema"):
        Store(path).records()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_reading_an_absent_database_does_not_create_it(tmp_path):
    path = tmp_path / "missing" / "analytics.db"
    assert Store(path).report()["totals"]["utterances"] == 0
    assert not path.exists()


def test_async_writer_persists_cumulative_accepted_recognition_on_cancel(
    tmp_path, analytics_session
):
    path = tmp_path / "analytics.db"
    session = analytics_session(path)
    identity = session.start(1)
    session.checkpoint(identity, "secured_capture", {"capture_s": 5})
    session.checkpoint(identity, "accepted_recognition", {"recognized_words": 9, "asr_audio_s": 5})
    session.finish(identity, "cancelled")
    drain(session)
    record = Store(path).records()[0]
    assert record["metrics"]["recognized_words"] == 9
    assert record["metrics"]["capture_s"] == 5
    assert record["outcome"] == "cancelled"
    assert len(Store(path).timeline(identity)) == 4
    assert not session.health["degraded"]


def test_real_sqlite_contention_retries_without_double_counting(tmp_path, analytics_session):
    path = tmp_path / "analytics.db"
    store = Store(path)
    store.register_run("seed", {})
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = analytics_session(path, retries=5)
        identity = session.start(1)
        session.finish(identity, "success", {"recognized_words": 8})
        time.sleep(0.15)
        # A bounded close reports unfinished work while the real lock is held.
        assert not session.close(timeout=0), session.health
    drain(session)
    assert store.report()["totals"]["recognized_words"] == 8
    assert len(store.timeline(identity)) == 2


def test_bounded_queue_and_persistent_contention_report_loss(tmp_path, analytics_session):
    path = tmp_path / "analytics.db"
    Store(path).register_run("seed", {})
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = analytics_session(path, queue_size=1, retries=0)
        started = time.monotonic()
        for identity in range(30):
            session.start(identity)
            session.finish(identity, "success")
        assert time.monotonic() - started < 0.5
        assert session.health["dropped_checkpoints"] > 0
    drain(session)
    assert session.health["degraded"]


def test_disabled_collection_performs_no_database_or_probe_work(tmp_path):
    path = tmp_path / "analytics.db"

    def forbidden():
        raise AssertionError("disabled profiling executed")

    session = AnalyticsSession(path, enabled=False, resource_probe=forbidden)
    session.start(1)
    session.finish(1, "success", {"recognized_words": 5})
    assert session.close()
    assert not path.exists()


def test_resource_summary_distinguishes_unavailable_values_from_zero():
    summary = ResourceSummary(10)
    summary.observe(
        {
            "cpu_seconds": 5.0,
            "resident_bytes": 100,
            "host_cpu_percent": 0,
            "gpu_utilization_percent": None,
        },
        observed_at=10,
    )
    summary.observe(
        {"cpu_seconds": 5.25, "resident_bytes": 200, "host_cpu_percent": 50}, observed_at=10.5
    )
    result = summary.metrics(11)
    assert result["app_cpu_s"] == 0.25
    assert result["app_rss_bytes_max"] == 200
    assert result["host_cpu_percent_avg"] == 50
    assert result["gpu_utilization_samples"] == 0
    assert "gpu_utilization_percent_avg" not in result
    assert result["resource_coverage"] == pytest.approx(2 / 3)


def test_equivalent_timezone_filters_select_the_same_instants(tmp_path):
    store = Store(tmp_path / "analytics.db")
    store.write_checkpoint(checkpoint())
    assert len(store.records(Filters(since="2026-01-01T07:00:00-05:00"))) == 1
    assert len(store.records(Filters(until="2026-01-01T07:00:00-05:00"))) == 0
    with pytest.raises(ValueError, match="timezone"):
        Filters(since="2026-01-01")


def test_liveness_recovery_preserves_unknown_process_and_checkpoint_timeline(tmp_path):
    store = Store(tmp_path / "analytics.db")
    store.register_run("run", {}, (123, 100.0))
    store.register_run("unknown", {}, (456, 200.0))
    store.write_checkpoint(checkpoint())
    other = checkpoint("unknown:1")
    other["run_id"] = "unknown"
    store.write_checkpoint(other)
    # An injected pure identity lookup expresses evidence without pretending to probe an OS.
    evidence = {(123, 100.0): False, (456, 200.0): None}
    assert store.recover_interrupted(lambda pid, started: evidence[(pid, started)]) == 1
    assert store.timeline("run:1")[-1]["outcome"] == "interrupted"
    assert store.records()[1]["outcome"] is None
    assert store.recover_interrupted(lambda pid, started: evidence[(pid, started)]) == 0


def test_resource_boundary_observations_cannot_hide_missed_intervals():
    summary = ResourceSummary(10)
    for _ in range(5):
        summary.observe({"resident_bytes": 200}, observed_at=10.1)
    assert summary.metrics(12)["resource_coverage"] == 0.2
    summary.observe({"cpu_seconds": 7, "reasons": {"gpu": "unsupported"}}, observed_at=12)
    assert "app_cpu_s" not in summary.metrics(12)
    assert summary.metrics(12)["app_cpu_samples"] == 1
    assert summary.context() == {"resource_availability": "gpu:unsupported"}


def test_privacy_rejection_also_applies_to_direct_database_writes(tmp_path):
    store = Store(tmp_path / "analytics.db")
    record = checkpoint()
    record["outcome"] = "private_transcript"
    with pytest.raises(ValueError, match="vocabulary"):
        store.write_checkpoint(record)
    assert not store.path.exists()


@pytest.mark.parametrize("outcome", ["cancelled", "copy_failed", "chord_failed"])
def test_numeric_pipeline_checkpoints_preserve_accepted_words_on_delivery_failure(
    tmp_path, outcome, analytics_session
):
    from stenographer.transcribe.pipeline import UtteranceRecord, analytics_metrics

    path = tmp_path / "analytics.db"
    session = analytics_session(path, resource_probe=None)
    record = UtteranceRecord(utt=1, started_at=123.5, source="hotkey")
    record.analytics_id = session.start(record.utt)
    record.capture_s = 3.0
    session.checkpoint(record.analytics_id, "secured_capture", analytics_metrics(record))
    record.recognized_words = count_words("Recognized words stay counted.")
    record.asr_audio_s = 3.0
    record.decode_ms = 52
    session.checkpoint(record.analytics_id, "accepted_recognition", analytics_metrics(record))
    record.final_words = 4
    if outcome == "chord_failed":
        record.copied_words = 4
        session.checkpoint(record.analytics_id, "clipboard_confirmed", analytics_metrics(record))
    record.failure = outcome
    session.finish(record.analytics_id, outcome, analytics_metrics(record))
    drain(session)
    report = Store(path).report()
    assert report["totals"]["recognized_words"] == 4
    assert report["totals"]["asr_audio_s"] == 3
    assert report["totals"]["chord_words"] == 0
    assert report["totals"]["copied_words"] == (4 if outcome == "chord_failed" else 0)
    persisted = Store(path).records()[0]
    assert "started_at" not in persisted["metrics"]
    assert "analytics_id" not in persisted["metrics"]
    assert persisted["outcome"] == outcome


def test_pipeline_metric_boundary_accepts_only_whitelisted_numeric_fields():
    from stenographer.analytics.metrics import METRICS
    from stenographer.transcribe.pipeline import UtteranceRecord, analytics_metrics

    record = UtteranceRecord(
        utt=999,
        started_at=1,
        stopped_at=2,
        source="private text",
        analytics_id="private id",
        outcome="private text",
        recognized_words=3,
    )
    metrics = analytics_metrics(record)
    assert metrics == {"recognized_words": 3, "ignored_busy_presses": 0}
    assert set(metrics) <= METRICS


def test_run_registration_recovers_after_initial_storage_failure(tmp_path, analytics_session):
    path = tmp_path / "analytics.db"
    Store(path).register_run("seed", {})
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = analytics_session(path, retries=0)
        deadline = time.monotonic() + 2
        while not session.health["write_failures"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session.health["write_failures"] == 1
    session.start(1)
    session.finish(1, "success", {"recognized_words": 5})
    drain(session)
    health = Store(path).health()
    assert health["runs"] == 2
    assert health["degraded"]
    assert Store(path).report()["totals"]["recognized_words"] == 5


def test_negotiated_capture_context_replaces_configured_device_and_survives_finish(
    tmp_path, analytics_session
):
    path = tmp_path / "analytics.db"
    session = analytics_session(path, context={"model": "medium.en", "device": "default"})
    identity = session.start(1)
    session.checkpoint(
        identity,
        "secured_capture",
        {"capture_s": 3},
        context={
            "device": "USB mic",
            "sample_rate": 48000,
            "channels": 1,
        },
    )
    session.finish(identity, "success", {"recognized_words": 4})
    drain(session)
    store = Store(path)
    record = store.records(Filters(device="USB mic"))[0]
    assert record["context"] == {
        "model": "medium.en",
        "device": "USB mic",
        "sample_rate": 48000,
        "channels": 1,
    }
    assert store.records(Filters(device="default")) == []
    assert record["revision"] == 2
    assert record["metrics"]["capture_s"] == 3


def test_checkpoint_context_rejects_private_fields_before_mutating_snapshot(
    tmp_path, analytics_session
):
    path = tmp_path / "analytics.db"
    session = analytics_session(path)
    identity = session.start(1)
    with pytest.raises(ValueError, match="context"):
        session.checkpoint(identity, "secured_capture", context={"transcript": "private"})
    session.finish(identity, "cancelled")
    drain(session)
    record = Store(path).records()[0]
    assert record["context"] == {}
    assert record["revision"] == 1


@pytest.mark.parametrize("learned", ["device", "outcome"])
def test_delayed_filter_match_deletes_earlier_incomplete_snapshot(tmp_path, learned):
    store = Store(tmp_path / "analytics.db")
    initial = checkpoint()
    initial["context"]["device"] = "default"
    store.write_checkpoint(initial)
    filters = Filters(device="USB mic") if learned == "device" else Filters(outcome="decode_failed")
    assert store.delete(filters) == 0
    update = checkpoint(revision=1, phase="terminal")
    update["outcome"] = "decode_failed"
    assert not store.write_checkpoint(update)
    assert store.records(Filters(source=None)) == []
    assert store.timeline(initial["id"]) == []
    later = checkpoint(revision=2, phase="terminal", recognized_words=8)
    later["outcome"] = "success"
    assert not store.write_checkpoint(later)


def test_completed_resource_window_discards_late_observations_and_caps_coverage():
    summary = ResourceSummary(10)
    summary.observe({"cpu_seconds": 5, "resident_bytes": 100}, observed_at=10.1)
    summary.observe({"cpu_seconds": 5.2, "resident_bytes": 200}, observed_at=10.3)
    summary.ended_at = 10.4
    assert not summary.observe({"cpu_seconds": 99, "resident_bytes": 999}, observed_at=11)
    metrics = summary.metrics(50)
    assert metrics["resource_window_s"] == pytest.approx(0.4)
    assert metrics["resource_expected_samples"] == 1
    assert metrics["resource_samples"] == 2
    assert metrics["app_cpu_s"] == pytest.approx(0.2)
    assert metrics["app_rss_bytes_max"] == 200


def test_queued_completed_utterance_never_profiles_writer_drain(tmp_path, analytics_session):
    path = tmp_path / "analytics.db"
    Store(path).register_run("seed", {})
    observations = []

    def probe():
        observations.append(1)
        return {"cpu_seconds": 10, "resident_bytes": 500}

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = analytics_session(path, retries=5, resource_probe=probe)
        identity = session.start(1)
        session.finish(identity, "success")
        time.sleep(0.55)
    drain(session)
    assert observations == []
    record = Store(path).records()[0]
    metrics = record["metrics"]
    assert metrics["resource_samples"] == 0
    assert metrics["resource_expected_samples"] == 1
    assert metrics["resource_boundary_samples"] == 0
    assert metrics["resource_boundary_missing"] == 2
    assert "app_cpu_s" not in metrics
    assert "app_rss_bytes_max" not in metrics
    assert record["context"]["resource_availability"] == "sampling:no_timely_samples"


def test_probe_completing_after_terminal_is_not_attributed(tmp_path, analytics_session):
    import threading

    entered = threading.Event()
    release = threading.Event()

    def probe():
        entered.set()
        assert release.wait(timeout=2)
        return {"cpu_seconds": 99, "resident_bytes": 999}

    path = tmp_path / "analytics.db"
    session = analytics_session(path, resource_probe=probe)
    try:
        identity = session.start(1)
        assert entered.wait(timeout=2)
        session.finish(identity, "success")
    finally:
        release.set()
    drain(session)
    metrics = Store(path).records()[0]["metrics"]
    assert metrics["resource_samples"] == 0
    assert metrics["resource_boundary_missing"] == 2
    assert "app_rss_bytes_max" not in metrics


def test_liveness_recovery_preserves_clean_run_end_and_checks_closed_incomplete_run(tmp_path):
    path = tmp_path / "analytics.db"
    store = Store(path)
    store.register_run("clean", {}, (1, 100))
    store.register_run("run", {}, (2, 200))
    store.update_health("clean", {}, ended=True)
    store.update_health("run", {}, ended=True)
    store.write_checkpoint(checkpoint())
    with sqlite3.connect(path) as connection:
        before = dict(connection.execute("SELECT run_id,ended_at FROM runs"))
    checked = []

    def dead(pid, _started):
        checked.append(pid)
        return False

    assert store.recover_interrupted(dead) == 1
    assert checked == [2]
    assert store.mark_interrupted("clean", process_confirmed_dead=True) == 0
    with sqlite3.connect(path) as connection:
        after = dict(connection.execute("SELECT run_id,ended_at FROM runs"))
    assert after == before
    assert store.recover_interrupted(dead) == 0
    assert checked == [2]


def test_first_host_cpu_percentage_cannot_include_the_previous_idle_interval():
    summary = ResourceSummary(10)
    summary.observe({"host_cpu_percent": 99}, observed_at=10.1)
    assert "host_cpu_percent_avg" not in summary.metrics(10.1)
    assert summary.metrics(10.1)["host_cpu_samples"] == 0
    summary.observe({"host_cpu_percent": 20}, observed_at=10.6)
    summary.observe({"host_cpu_percent": 40}, observed_at=11.1)
    assert summary.metrics(11.1)["host_cpu_percent_avg"] == 30
    assert summary.metrics(11.1)["host_cpu_samples"] == 2


def test_observation_in_the_same_clock_tick_as_terminal_is_not_attributed():
    """Seen to FAIL against the strict ``observed_at > ended_at`` guard.

    A 15.6 ms ``time.monotonic()`` (Windows, Python 3.12) stamps the terminal
    checkpoint and a probe that returned after it with the same value.
    """
    summary = ResourceSummary(10)
    summary.ended_at = 12
    assert not summary.observe({"cpu_seconds": 1, "resident_bytes": 1}, observed_at=12)
    assert summary.observations == 0


def test_checkpoint_advancement_freezes_snapshots_and_shares_terminal_window():
    from stenographer.analytics.checkpoints import Checkpoint, QueuedCheckpoint, advance_checkpoint

    measurements = {"capture_s": 3}
    first = Checkpoint("id", "run", "hotkey", "start", "start", 10, metrics=measurements)
    measurements["capture_s"] = 99
    window = ResourceSummary(first.monotonic_started)
    queued = QueuedCheckpoint(first, window)
    second = advance_checkpoint(
        first,
        "accepted_recognition",
        updated_at="later",
        monotonic_now=11,
        metrics={"recognized_words": 4},
        context={"sample_rate": 16000},
    )
    terminal = advance_checkpoint(
        second,
        "terminal",
        updated_at="end",
        monotonic_now=12,
        outcome="success",
    )
    final = QueuedCheckpoint(terminal, queued.resource)
    final.resource.ended_at = terminal.monotonic_finished
    assert queued.resource.ended_at == 12
    assert first.metrics == {"capture_s": 3} and first.revision == 0
    assert second.metrics == {"capture_s": 3, "recognized_words": 4}
    assert terminal.revision == 2 and terminal.outcome == "success"
    assert terminal.context == {"sample_rate": 16000}
    assert "decode_ms" not in terminal.to_store()["metrics"]
    with pytest.raises(TypeError):
        first.metrics["capture_s"] = 1
    payload = terminal.to_store()
    payload["metrics"]["capture_s"] = 100
    assert terminal.metrics["capture_s"] == 3
    with pytest.raises(ValueError, match="regress"):
        advance_checkpoint(second, "secured_capture", updated_at="bad", monotonic_now=13)
