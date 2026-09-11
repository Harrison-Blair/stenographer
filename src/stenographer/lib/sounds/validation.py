# SPDX-License-Identifier: GPL-3.0-or-later
"""Containment and bounded PCM validation for sound-pack assets."""

from __future__ import annotations

import logging
import pathlib
import wave

from stenographer.lib.logging.pipeline import fmt_event, log_failure
from stenographer.lib.sounds.constants import (
    _MAX_DURATION_SECONDS,
    _MAX_SAMPLE_RATE,
    _MIN_SAMPLE_RATE,
    _VALID_SAMPLE_WIDTHS,
)

logger = logging.getLogger(__name__)


def _resolved_within(path: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Resolve an existing path only when it remains inside *root*."""
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _wav_header_ok(
    channels: int,
    sample_width: int,
    sample_rate: int,
    frame_count: int,
    compression: str,
) -> bool:
    """Whether WAV header fields describe the bounded PCM cue subset. PURE."""
    return (
        compression == "NONE"
        and channels in (1, 2)
        and sample_width in _VALID_SAMPLE_WIDTHS
        and _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE
        and frame_count > 0
        and frame_count < sample_rate * _MAX_DURATION_SECONDS
    )


def _valid_wav(path: pathlib.Path) -> bool:
    """Validate the bounded PCM WAV subset accepted for lifecycle cues.

    Header bounds are checked before any payload is read, so an oversized or
    hostile frame count never allocates.
    """
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            compression = wav.getcomptype()
            if not _wav_header_ok(channels, sample_width, sample_rate, frame_count, compression):
                return False
            frames = wav.readframes(frame_count)
    except (EOFError, MemoryError, OSError, wave.Error) as exc:
        # A cue that silently fails validation is indistinguishable from a
        # muted daemon, so name the file and the reason it was rejected.
        log_failure(logger, logging.WARNING, "feedback: cue_invalid", exc, safe=True, path=path)
        return False

    if not _wav_payload_ok(len(frames), frame_count, channels, sample_width):
        logger.warning(
            fmt_event(
                "feedback",
                "cue_invalid",
                path=path,
                reason="truncated_payload",
                frame_bytes=len(frames),
                frame_count=frame_count,
                channels=channels,
                sample_width=sample_width,
            )
        )
        return False
    return True


def _wav_payload_ok(frames_len: int, frame_count: int, channels: int, sample_width: int) -> bool:
    """A truncated payload must fail validation even when the header parses. PURE."""
    return frames_len == frame_count * channels * sample_width
