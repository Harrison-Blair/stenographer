# SPDX-License-Identifier: GPL-3.0-or-later
"""The gate → decode → format core shared by the daemon and ``transcribe``.

One utterance produces exactly one INFO summary line, whether it came from the
hotkey or from ``stenographer transcribe <file>``. Both paths fill the same
:class:`UtteranceRecord` as their phases complete and hand it to
:func:`log_summary`, so a file run is directly comparable with a live one; both
also downmix through :func:`downmix` and format through :func:`transcript_text`,
so neither can drift from the other's audio or spacing.

The record is filled in from several threads (hotkey, pipeline) but only ever
for the one utterance in flight, which the daemon's state lock serialises.
:func:`summary_fields`, :func:`downmix` and :func:`transcript_text` are pure;
the two ``log_*`` helpers exist so the ``fmt_event`` call sites stay literal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stenographer.transcribe.format import format_transcript
from stenographer.utils.logging_setup import fmt_event

if TYPE_CHECKING:
    import numpy as np

    from stenographer.audio import GateStats
    from stenographer.transcribe.model import TranscriptionResult

log = logging.getLogger(__name__)


@dataclass
class UtteranceRecord:
    """Everything measured about one utterance, in summary-line order.

    Every field but ``utt`` is optional: an utterance that fails its gate never
    reaches a decode, and a rendered ``None`` field is dropped rather than
    printed, so one record serves every early exit.
    """

    utt: int
    source: str | None = None
    mode: str | None = None
    outcome: str | None = None
    activate_ms: float | None = None
    capture_s: float | None = None
    in_frames: int | None = None
    out_frames: int | None = None
    overflow: bool | None = None
    capped: bool | None = None
    gate: str | None = None
    peak_rms: float | None = None
    frames_above: int | None = None
    cold: bool | None = None
    load_ms: float | None = None
    lock_wait_ms: float | None = None
    decode_ms: float | None = None
    vad_frames: int | None = None
    segments: int | None = None
    words: int | None = None
    chars_raw: int | None = None
    chars_out: int | None = None
    copy_ms: float | None = None
    release_wait_ms: float | None = None
    release_timeout: bool | None = None
    total_ms: float | None = None


def summary_fields(record: UtteranceRecord) -> dict[str, object]:
    """Render *record* as the summary line's ordered fields. PURE.

    Durations are rounded here rather than at each measuring site, so every
    phase records raw ``perf_counter`` arithmetic and only the line decides how
    much precision is worth reading. Flags become ``0``/``1`` to match the rest
    of the log; ``None`` stays ``None`` for ``fmt_event`` to drop.
    """
    return {
        "utt": record.utt,
        "source": record.source,
        "mode": record.mode,
        "outcome": record.outcome,
        "activate_ms": _ms(record.activate_ms),
        "capture_s": _seconds(record.capture_s),
        "in_frames": record.in_frames,
        "out_frames": record.out_frames,
        "overflow": _flag(record.overflow),
        "capped": _flag(record.capped),
        "gate": record.gate,
        "peak_rms": None if record.peak_rms is None else round(record.peak_rms, 6),
        "frames_above": record.frames_above,
        "cold": _flag(record.cold),
        "load_ms": _ms(record.load_ms),
        "lock_wait_ms": _ms(record.lock_wait_ms),
        "decode_ms": _ms(record.decode_ms),
        "vad_frames": record.vad_frames,
        "segments": record.segments,
        "words": record.words,
        "chars_raw": record.chars_raw,
        "chars_out": record.chars_out,
        "copy_ms": _ms(record.copy_ms),
        "release_wait_ms": _ms(record.release_wait_ms),
        "release_timeout": _flag(record.release_timeout),
        "total_ms": _ms(record.total_ms),
    }


def log_summary(record: UtteranceRecord) -> None:
    """Emit the one INFO line that describes the whole utterance."""
    log.info(fmt_event("pipeline", "utterance", **summary_fields(record)))


def log_gate(stats: GateStats) -> None:
    """Report the energy gate's numbers and its verdict from one computation."""
    log.info(
        fmt_event(
            "audio",
            "speech_gate",
            verdict="pass" if stats.passed else "fail",
            peak_rms=round(stats.peak_rms, 6),
            mean_rms=round(stats.mean_rms, 6),
            frames_total=stats.frames_total,
            frames_above=stats.frames_above,
            threshold=stats.threshold,
        )
    )


def downmix(samples: np.ndarray) -> np.ndarray:
    """Reduce a 2-D capture to mono by keeping channel 0. PURE.

    Channel 0, not the channel mean: that is what the PortAudio callback keeps,
    and averaging a stereo mic whose second channel is silent or out of phase
    halves or cancels the speech the gate then has to find.
    """
    if samples.ndim != 2:
        return samples.reshape(-1)
    return samples[:, 0]


def transcript_text(result: TranscriptionResult, *, raw: bool = False) -> str:
    """Format a decode result for delivery. PURE.

    The trailing space belongs to dictation: consecutive utterances pasted at
    the cursor must not run together. ``raw`` hands back exactly what the
    decoder produced.
    """
    if raw:
        return result.text
    return format_transcript(result.text, trailing_space=True)


def _flag(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _seconds(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
