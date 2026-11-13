# SPDX-License-Identifier: GPL-3.0-or-later
"""Session storage tests without audio hardware."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest
import soundfile

from stenographer.lib.live.session_writer import SessionWriter
from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.platform.linux.pw_record import PwRecordDecoder

_STARTED = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
_WALL = "2026-03-02T04:05:07+00:00"


def _open_writer(root, started_at=_STARTED):
    writer = SessionWriter.open(root, started_at)
    return writer


def _line(
    *,
    start: float = 1.0,
    end: float = 2.0,
    source: str = "mic",
    speaker_id: str = "you",
    label: str = "You",
    text: str = "recognized phrase",
) -> TranscriptLine:
    return TranscriptLine(
        start=start,
        end=end,
        wall=_WALL,
        source=source,
        speaker_id=speaker_id,
        label=label,
        text=text,
    )


def test_open_uses_utc_timestamp_restrictive_folder_and_collision_suffix(tmp_path):
    started_at = datetime(2026, 3, 2, 14, 35, 6, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    first = _open_writer(tmp_path, started_at)
    first.close()
    second = _open_writer(tmp_path, started_at)
    second.close()

    assert first.path == tmp_path / "sessions" / "20260302T090506Z"
    assert second.path == tmp_path / "sessions" / "20260302T090506Z-2"
    assert first.path.stat().st_mode & 0o777 == 0o700
    assert second.path.stat().st_mode & 0o777 == 0o700


def test_write_audio_round_trips_float_samples_and_creates_private_flac(tmp_path):
    writer = _open_writer(tmp_path)
    samples = np.asarray([0.0, 0.5, -0.25, 0.75, -1.0], dtype=np.float32)
    audio_path = writer.path / "mic.flac"

    assert not audio_path.exists()
    writer.write_audio("mic", samples[:2])
    writer.write_audio("mic", samples[2:])
    writer.close()

    actual, rate = soundfile.read(audio_path, dtype="float32")
    assert rate == 16000
    assert len(actual) == len(samples)
    np.testing.assert_allclose(actual, samples, atol=1e-6)
    assert audio_path.stat().st_mode & 0o777 == 0o600


def test_write_silence_creates_requested_number_of_zero_samples(tmp_path):
    writer = _open_writer(tmp_path)
    writer.write_silence("system", 0.25)
    writer.close()

    silence, rate = soundfile.read(writer.path / "system.flac", dtype="float32")
    assert rate == 16000
    assert len(silence) == 4000
    assert np.count_nonzero(silence) == 0


def test_append_line_flushes_jsonl_and_relabel_appends_a_rename_record(tmp_path):
    writer = _open_writer(tmp_path)
    line = _line(
        start=2.5,
        end=3.25,
        source="system",
        speaker_id="speaker-1",
        label="Speaker 1",
        text="a phrase",
    )

    writer.append_line(line)
    transcript_path = writer.path / "transcript.jsonl"
    first_record = json.loads(transcript_path.read_text(encoding="utf-8"))
    writer.relabel({"speaker-1": "Alice"})
    records = [
        json.loads(item) for item in transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    writer.close()

    assert first_record == {
        "start": 2.5,
        "end": 3.25,
        "wall": _WALL,
        "source": "system",
        "speaker_id": "speaker-1",
        "label": "Speaker 1",
        "text": "a phrase",
    }
    assert records == [
        first_record,
        {"type": "rename", "labels": {"speaker-1": "Alice"}},
    ]
    assert transcript_path.stat().st_mode & 0o777 == 0o600


def test_close_writes_markdown_with_duration_sources_and_final_labels(tmp_path):
    writer = _open_writer(tmp_path)
    writer.write_silence("system", 4.0)
    writer.append_line(
        _line(
            start=2.5,
            end=3.25,
            source="system",
            speaker_id="speaker-1",
            label="Speaker 1",
            text="saved phrase",
        )
    )
    writer.relabel({"speaker-1": "Alice"})
    writer.close()

    markdown_path = writer.path / "transcript.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Started: 2026-03-02T04:05:06Z" in markdown
    assert "Duration: 00:00:04" in markdown
    assert "Sources: system" in markdown
    assert "[00:00:02] **Alice:** saved phrase" in markdown
    assert markdown_path.stat().st_mode & 0o777 == 0o600


def test_close_logs_only_session_metrics_and_never_phrase_text(tmp_path, caplog):
    writer = _open_writer(tmp_path)
    writer.write_silence("mic", 0.5)
    writer.append_line(_line(text="private transcript words"))

    with caplog.at_level(logging.INFO, logger="stenographer.lib.live.session_writer"):
        writer.close()

    assert str(writer.path) in caplog.text
    assert "line_count=1" in caplog.text
    assert "mic" in caplog.text
    assert "0.5" in caplog.text
    assert "private transcript words" not in caplog.text, "transcript text appeared in logs"


def test_audio_and_transcript_writes_are_safe_from_three_threads(tmp_path):
    writer = _open_writer(tmp_path)
    thread_count = 3
    blocks = 100
    block_size = 320
    first_write = threading.Barrier(thread_count)

    def write_source(thread_index: int) -> None:
        block = np.full(block_size, 0.25, dtype=np.float32)
        first_write.wait()
        writer.write_audio("mic", block)
        for index in range(blocks):
            writer.write_audio("mic", block)
            writer.append_line(
                _line(start=float(thread_index * blocks + index), text=f"phrase {index}")
            )

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(write_source, index) for index in range(thread_count)]
        for future in futures:
            future.result()

    writer.close()

    audio, rate = soundfile.read(writer.path / "mic.flac", dtype="float32")
    assert rate == 16000
    assert len(audio) == thread_count * (blocks + 1) * block_size
    np.testing.assert_allclose(audio, 0.25, atol=1e-6)

    records = (writer.path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == thread_count * blocks
    assert all(json.loads(record)["source"] == "mic" for record in records)


def test_a_failed_rename_write_leaves_the_name_out_of_the_markdown(tmp_path):
    writer = _open_writer(tmp_path)
    writer.append_line(
        _line(
            start=0.25,
            end=0.5,
            source="system",
            speaker_id="speaker-1",
            label="Speaker 1",
            text="words",
        )
    )
    jsonl = writer._jsonl

    class FailingFile:
        def write(self, _text):
            raise OSError("disk full")

    writer._jsonl = FailingFile()
    with pytest.raises(OSError, match="disk full"):
        writer.relabel({"speaker-1": "Alice"})
    writer._jsonl = jsonl
    writer.close()

    markdown = (writer.path / "transcript.md").read_text(encoding="utf-8")
    assert "Speaker 1" in markdown
    assert "Alice" not in markdown


def test_a_decoded_block_from_bytes_with_a_nan_is_saved_and_a_later_write_succeeds(tmp_path):
    first = np.array([0.25, np.nan, -0.5, *([0.0] * 509)], dtype="<f4")
    second = np.full(512, 0.125, dtype=np.float32)
    decoder = PwRecordDecoder()
    [block] = decoder.feed(first.tobytes())
    writer = _open_writer(tmp_path)

    writer.write_audio("system", block)
    writer.write_audio("system", second)
    writer.close()

    audio, rate = soundfile.read(writer.path / "system.flac", dtype="float32")
    assert rate == 16000
    assert audio.size == 1024
    np.testing.assert_allclose(audio[:3], [0.25, 0.0, -0.5], atol=1e-6)
    np.testing.assert_allclose(audio[512:], 0.125, atol=1e-6)
