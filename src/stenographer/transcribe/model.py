# SPDX-License-Identifier: GPL-3.0-or-later
"""faster-whisper wrapper: fixed anti-hallucination decode stack.

All testable logic lives in the pure helpers so the ``WhisperModel`` call never
needs mocking; faster-whisper is imported inside ``Model.__init__`` so the cache
probe and download helpers stay light.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stenographer.constants import SAMPLE_RATE

if TYPE_CHECKING:
    import numpy as np

    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 128
_HALLUCINATION_SILENCE_SECONDS = 2.0
_WORDS_PER_VAD_SECOND = 8
_MIN_WORD_LIMIT = 12
_AUTO_CPU_THREAD_CAP = 8
_CPU_THREAD_FALLBACK = 4
_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 100,
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 250,
}


class PathologicalOutputError(RuntimeError):
    """The decoder returned structurally invalid or implausibly dense output."""


@dataclass(frozen=True)
class WordInfo:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class SegmentInfo:
    start: float
    end: float
    text: str
    no_speech_prob: float
    words: list[WordInfo] = field(default_factory=list)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: float
    segments: list[SegmentInfo] = field(default_factory=list)


class Model:
    def __init__(self, cfg: AsrConfig) -> None:
        from faster_whisper import WhisperModel

        from stenographer.platform import current_platform

        # An explicit thread count short-circuits the host probe entirely.
        cpu_threads = cfg.cpu_threads or resolve_cpu_threads(
            0, current_platform().physical_core_count()
        )
        started = time.monotonic()
        self._impl = WhisperModel(
            cfg.model,
            device="auto",
            compute_type=cfg.compute_type,
            cpu_threads=cpu_threads,
            local_files_only=True,
        )
        self._cfg = cfg
        log.info(
            "asr: model loaded elapsed_ms=%d cpu_threads=%d",
            round((time.monotonic() - started) * 1000),
            cpu_threads,
        )

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        started = time.monotonic()
        if samples.size == 0:
            log.info(
                "asr: decode complete elapsed_ms=%d audio_frames=0 vad_frames=0 "
                "segments=0 words=0 transcript_chars=0",
                round((time.monotonic() - started) * 1000),
            )
            return TranscriptionResult(text="", duration_seconds=0.0, segments=[])
        if samples.ndim == 2:
            samples = samples.mean(axis=1) if samples.shape[1] > 1 else samples.squeeze(-1)
        cfg = self._cfg
        audio_seconds = samples.shape[0] / SAMPLE_RATE
        segments_iter, info = self._impl.transcribe(
            samples,
            language="en",
            beam_size=cfg.beam_size,
            temperature=0.0,
            no_repeat_ngram_size=3,
            vad_filter=cfg.vad_filter,
            vad_parameters=_VAD_PARAMETERS,
            no_speech_threshold=cfg.silence_threshold,
            hallucination_silence_threshold=_HALLUCINATION_SILENCE_SECONDS,
            max_new_tokens=_token_budget(_MAX_NEW_TOKENS, audio_seconds),
            condition_on_previous_text=False,
            hotwords=(cfg.hotwords or None),
            initial_prompt=(cfg.initial_prompt or None),
            word_timestamps=True,
        )
        segments = [
            SegmentInfo(
                start=float(seg.start),
                end=float(seg.end),
                text=seg.text,
                no_speech_prob=float(seg.no_speech_prob),
                words=[
                    WordInfo(float(w.start), float(w.end), w.word, float(w.probability))
                    for w in seg.words or ()
                ],
            )
            for seg in segments_iter
        ]
        vad_seconds = float(getattr(info, "duration_after_vad", audio_seconds))
        result = _assemble(
            segments,
            silence_threshold=cfg.silence_threshold,
            audio_seconds=audio_seconds,
            vad_seconds=vad_seconds,
        )
        log.info(
            "asr: decode complete elapsed_ms=%d audio_frames=%d vad_frames=%d "
            "segments=%d words=%d transcript_chars=%d",
            round((time.monotonic() - started) * 1000),
            samples.shape[0],
            round(vad_seconds * SAMPLE_RATE),
            len(result.segments),
            sum(len(s.words) for s in result.segments),
            len(result.text),
        )
        return result

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl


def resolve_cpu_threads(configured: int, physical_cores: int | None) -> int:
    """Explicit value passes through; else *physical_cores* capped at eight,
    falling back to four when the host could not count them."""
    if configured:
        return configured
    if physical_cores is None or physical_cores < 1:
        return _CPU_THREAD_FALLBACK
    return min(_AUTO_CPU_THREAD_CAP, physical_cores)


def _token_budget(configured_max: int, audio_seconds: float) -> int:
    """Bound generated tokens to a small fixed allowance plus audio duration."""
    return min(configured_max, 16 + math.ceil(_WORDS_PER_VAD_SECOND * audio_seconds))


def _validate_output(
    *,
    segment_timestamps: list[tuple[float, float]],
    word_timestamps: list[tuple[float, float]],
    word_count: int,
    audio_seconds: float,
    vad_seconds: float,
) -> None:
    """Reject invalid timestamps and decoder-runaway word density. Messages carry
    no transcript content so pathological output never leaks dictated text."""
    if not math.isfinite(vad_seconds) or vad_seconds < 0:
        raise PathologicalOutputError("invalid VAD duration")
    tolerance = 1.0
    for start, end in (*segment_timestamps, *word_timestamps):
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or end > audio_seconds + tolerance
        ):
            raise PathologicalOutputError("invalid decoder timestamp")
    word_limit = max(_MIN_WORD_LIMIT, math.ceil(_WORDS_PER_VAD_SECOND * vad_seconds))
    if word_count > word_limit:
        raise PathologicalOutputError(
            f"decoder word density exceeded limit ({word_count} > {word_limit})"
        )


def _assemble(
    segments: list[SegmentInfo],
    *,
    silence_threshold: float,
    audio_seconds: float,
    vad_seconds: float,
) -> TranscriptionResult:
    """Gate probable-silence segments, validate, and assemble the transcript."""
    kept = [seg for seg in segments if seg.no_speech_prob < silence_threshold]
    text = "".join(seg.text for seg in kept).strip()
    word_timestamps = [(w.start, w.end) for seg in kept for w in seg.words]
    _validate_output(
        segment_timestamps=[(seg.start, seg.end) for seg in kept],
        word_timestamps=word_timestamps,
        word_count=len(word_timestamps),
        audio_seconds=audio_seconds,
        vad_seconds=vad_seconds,
    )
    return TranscriptionResult(text=text, duration_seconds=audio_seconds, segments=kept)


def is_model_cached(model_id: str) -> bool:
    """True if the model's ``config.json`` is in the local HF cache (no network).

    Delegate cache layout and environment resolution to huggingface_hub so this
    stays aligned with model loading and ``snapshot_download``.
    """
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(model_id, "config.json")
    return isinstance(cached, str)


def download_model(model_id: str) -> None:
    """Fetch the model into the local HF cache using the fixed allow-list."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        model_id,
        allow_patterns=[
            "*.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    )
