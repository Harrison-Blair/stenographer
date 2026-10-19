# SPDX-License-Identifier: GPL-3.0-or-later
"""Write live-session audio and transcripts to a private session folder."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from stenographer.lib.live.transcript_line import TranscriptLine
from stenographer.lib.logging.pipeline import fmt_event

log = logging.getLogger(__name__)
_SAMPLE_RATE = 16000


class SessionWriter:
    def __init__(self, path: Path, started_at: datetime) -> None:
        self.path = path
        self.started_at = started_at
        self._lock = threading.RLock()
        self._audio: dict[str, sf.SoundFile] = {}
        self._source_samples: dict[str, int] = {}
        self._lines: list[TranscriptLine] = []
        self._labels: dict[str, str] = {}
        self._closed = False
        jsonl_path = self.path / "transcript.jsonl"
        fd = os.open(jsonl_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(jsonl_path, 0o600)
        self._jsonl = os.fdopen(fd, "a", encoding="utf-8", newline="\n")

    @classmethod
    def open(cls, root: str | Path, started_at: datetime) -> SessionWriter:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        else:
            started_at = started_at.astimezone(UTC)

        sessions = Path(root) / "sessions"
        sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
        base = started_at.strftime("%Y%m%dT%H%M%SZ")
        suffix = 1
        while True:
            name = base if suffix == 1 else f"{base}-{suffix}"
            path = sessions / name
            try:
                path.mkdir(mode=0o700)
                break
            except FileExistsError:
                suffix += 1
        os.chmod(path, 0o700)
        return cls(path, started_at)

    def write_audio(self, source: str, samples: np.ndarray) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("session writer is closed")
            samples = np.asarray(samples, dtype=np.float32)
            if samples.size == 0:
                return
            audio = self._audio.get(source)
            if audio is None:
                path = self.path / f"{source}.flac"
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                try:
                    audio = sf.SoundFile(
                        path,
                        mode="w",
                        samplerate=_SAMPLE_RATE,
                        channels=1,
                        format="FLAC",
                        subtype="PCM_24",
                    )
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                os.chmod(path, 0o600)
                self._audio[source] = audio
                self._source_samples[source] = 0
            audio.write(samples)
            audio.flush()
            self._source_samples[source] += len(samples)

    def write_silence(self, source: str, seconds: float) -> None:
        sample_count = round(seconds * _SAMPLE_RATE)
        if sample_count <= 0:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("session writer is closed")
            silence = np.zeros(min(sample_count, _SAMPLE_RATE), dtype=np.float32)
            while sample_count:
                count = min(sample_count, len(silence))
                self.write_audio(source, silence[:count])
                sample_count -= count

    def append_line(self, line: TranscriptLine) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("session writer is closed")
            self._jsonl.write(json.dumps(asdict(line), ensure_ascii=False) + "\n")
            self._jsonl.flush()
            self._lines.append(line)

    def relabel(self, labels: Mapping[str, str]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("session writer is closed")
            changes = dict(labels)
            self._labels.update(changes)
            self._jsonl.write(
                json.dumps({"type": "rename", "labels": changes}, ensure_ascii=False) + "\n"
            )
            self._jsonl.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for audio in self._audio.values():
                audio.close()
            self._jsonl.close()
            self._write_markdown()
            self._closed = True

            source_lines: dict[str, int] = {}
            for line in self._lines:
                source_lines[line.source] = source_lines.get(line.source, 0) + 1
            audio_seconds = {
                source: samples / _SAMPLE_RATE for source, samples in self._source_samples.items()
            }
            log.info(
                fmt_event(
                    "live",
                    "session_saved",
                    folder=self.path,
                    line_count=len(self._lines),
                    source_line_counts=source_lines,
                    audio_seconds=audio_seconds,
                )
            )

    def _write_markdown(self) -> None:
        duration = max(self._source_samples.values(), default=0) / _SAMPLE_RATE
        whole_seconds = int(duration)
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        sources = list(
            dict.fromkeys([*self._source_samples, *(line.source for line in self._lines)])
        )
        lines = [
            "# Session transcript",
            "",
            f"- Started: {self.started_at.isoformat().replace('+00:00', 'Z')}",
            f"- Duration: {hours:02d}:{minutes:02d}:{seconds:02d}",
            f"- Sources: {', '.join(sources)}",
            "",
        ]
        for line in self._lines:
            timestamp = int(line.start)
            hours, remainder = divmod(timestamp, 3600)
            minutes, seconds = divmod(remainder, 60)
            label = self._labels.get(line.speaker_id, line.label)
            lines.append(f"[{hours:02d}:{minutes:02d}:{seconds:02d}] **{label}:** {line.text}")
        content = "\n".join(lines) + "\n"

        fd, temporary_name = tempfile.mkstemp(prefix=".transcript-", suffix=".tmp", dir=self.path)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path / "transcript.md")
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
