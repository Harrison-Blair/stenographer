# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode unsupported soundfile formats through system FFmpeg binaries."""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from stenographer.lib.logging.pipeline import fmt_event

log = logging.getLogger(__name__)


class SubprocessFfmpegDecoder:
    """Run ffmpeg without a shell and stream mono 16 kHz float32 samples."""

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def duration(self, path: Path) -> float | None:
        if shutil.which("ffprobe") is None:
            return None
        started = time.perf_counter()
        log.info(fmt_event("files", "external_process_started", process="ffprobe"))
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.info(
                fmt_event(
                    "files",
                    "external_process_finished",
                    process="ffprobe",
                    error=type(exc).__name__,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
            )
            return None
        log.info(
            fmt_event(
                "files",
                "external_process_finished",
                process="ffprobe",
                exit_code=result.returncode,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        )
        if result.returncode != 0:
            return None
        try:
            value = float(result.stdout.strip())
        except ValueError:
            return None
        return value if math.isfinite(value) and value >= 0 else None

    def decode(self, path: Path, *, block_frames: int = 65536) -> Iterator[np.ndarray]:
        if block_frames <= 0:
            raise ValueError("block_frames must be greater than zero")
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-nostdin",
                "-i",
                str(path),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        process_id = process.pid
        started = time.perf_counter()
        log.info(fmt_event("files", "external_process_started", process="ffmpeg", pid=process_id))
        assert process.stdout is not None
        pending = b""
        finished = False
        try:
            while chunk := process.stdout.read(block_frames * 4):
                data = pending + chunk
                aligned_size = len(data) - len(data) % 4
                if aligned_size:
                    yield np.frombuffer(data[:aligned_size], dtype="<f4").copy()
                pending = data[aligned_size:]
            return_code = process.wait()
            log.info(
                fmt_event(
                    "files",
                    "external_process_finished",
                    process="ffmpeg",
                    pid=process_id,
                    exit_code=return_code,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
            )
            finished = True
            if pending:
                raise RuntimeError("ffmpeg returned incomplete float32 audio samples")
            if return_code != 0:
                raise RuntimeError(f"ffmpeg exited with status {return_code}")
        finally:
            process.stdout.close()
            if process.pid == process_id and process.poll() is None:
                process.terminate()
                process.wait()
                if not finished:
                    log.info(
                        fmt_event(
                            "files",
                            "external_process_finished",
                            process="ffmpeg",
                            pid=process_id,
                            exit_code=process.returncode,
                            cancelled=1,
                            duration_ms=round((time.perf_counter() - started) * 1000),
                        )
                    )
