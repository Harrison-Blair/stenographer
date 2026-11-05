# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe, decode, downmix, and resample file audio."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.streaming_resampler import StreamingResampler
from stenographer.lib.platform.ffmpeg_decoder import FfmpegDecoder


@dataclass(frozen=True)
class MediaInfo:
    """Media facts that a browser can display before it queues a job."""

    path: Path
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    uses_ffmpeg: bool
    needs_ffmpeg: bool


def inspect_media(path: str | Path, decoder: FfmpegDecoder) -> MediaInfo:
    """Return duration and decode route, including a missing-ffmpeg status."""
    source = Path(path).expanduser()
    if source.suffix.lower() in {".m4a", ".aac"}:
        return _ffmpeg_media_info(source, decoder)
    try:
        info = soundfile.info(str(source))
    except (OSError, RuntimeError, ValueError):
        return _ffmpeg_media_info(source, decoder)
    if info.samplerate <= 0 or info.channels <= 0 or info.frames < 0:
        return _ffmpeg_media_info(source, decoder)
    return MediaInfo(
        path=source,
        duration_seconds=info.frames / info.samplerate,
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        uses_ffmpeg=False,
        needs_ffmpeg=False,
    )


def _ffmpeg_media_info(path: Path, decoder: FfmpegDecoder) -> MediaInfo:
    available = decoder.available()
    return MediaInfo(
        path=path,
        duration_seconds=decoder.duration(path) if available else None,
        sample_rate=SAMPLE_RATE if available else None,
        channels=1 if available else None,
        uses_ffmpeg=True,
        needs_ffmpeg=not available,
    )


def iter_media_audio(
    path: str | Path,
    info: MediaInfo,
    decoder: FfmpegDecoder,
    *,
    block_frames: int = 65536,
) -> Generator[np.ndarray]:
    """Yield mono float32 chunks at 16 kHz without buffering the whole file."""
    if info.needs_ffmpeg:
        raise RuntimeError("needs ffmpeg")
    source = Path(path).expanduser()
    if info.uses_ffmpeg:
        yield from decoder.decode(source, block_frames=block_frames)
        return

    with soundfile.SoundFile(str(source)) as audio:
        resampler = StreamingResampler(int(audio.samplerate), SAMPLE_RATE)
        for block in audio.blocks(
            blocksize=block_frames,
            dtype="float32",
            always_2d=True,
        ):
            mono = np.mean(block, axis=1, dtype=np.float32)
            output = resampler.process(mono)
            if output.size:
                yield output
        remaining = resampler.flush()
        if remaining.size:
            yield remaining
