# SPDX-License-Identifier: GPL-3.0-or-later
"""faster-whisper wrapper: fixed anti-hallucination decode stack (§4.5/§4.6).

All testable logic lives in the pure helpers so the ``WhisperModel`` call never
needs mocking; faster-whisper is imported inside ``Model.__init__`` so the cache
probe and download helpers stay light.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from stenographer_v2.config import AsrConfig

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
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

        cpu_threads = resolve_cpu_threads(cfg.cpu_threads)
        self._impl = WhisperModel(
            cfg.model,
            device="auto",
            compute_type=cfg.compute_type,
            cpu_threads=cpu_threads,
            local_files_only=True,
        )
        self._cfg = cfg
        log.info("ASR model loaded: id=%s cpu_threads=%d", cfg.model, cpu_threads)

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        if samples.size == 0:
            return TranscriptionResult(text="", duration_seconds=0.0, segments=[])
        if samples.ndim == 2:
            samples = samples.mean(axis=1) if samples.shape[1] > 1 else samples.squeeze(-1)
        cfg = self._cfg
        audio_seconds = samples.shape[0] / _SAMPLE_RATE
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
            "asr: audio=%.3fs vad=%.3fs segments=%d words=%d",
            audio_seconds,
            vad_seconds,
            len(result.segments),
            sum(len(s.words) for s in result.segments),
        )
        return result

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl


def resolve_cpu_threads(
    configured: int,
    *,
    affinity: set[int] | None = None,
    topology_root: Path = Path("/sys/devices/system/cpu"),
) -> int:
    """Explicit value passes through; else count affinity-visible physical cores
    (unique package/core pairs), capped at eight, falling back to four."""
    if configured:
        return configured
    if affinity is None:
        try:
            affinity = set(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            return _CPU_THREAD_FALLBACK
    if not affinity:
        return _CPU_THREAD_FALLBACK
    physical: set[tuple[str, str]] = set()
    try:
        for cpu in affinity:
            topology = topology_root / f"cpu{cpu}" / "topology"
            package = (topology / "physical_package_id").read_text(encoding="ascii").strip()
            core = (topology / "core_id").read_text(encoding="ascii").strip()
            physical.add((package, core))
    except (OSError, ValueError):
        return _CPU_THREAD_FALLBACK
    return min(_AUTO_CPU_THREAD_CAP, len(physical)) or _CPU_THREAD_FALLBACK


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
    no transcript content so pathological output never leaks dictated text (§4.6)."""
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
    """True if the model's ``config.json`` is in the local HF cache (no network)."""
    from huggingface_hub import try_to_load_from_cache

    return isinstance(try_to_load_from_cache(repo_id=model_id, filename="config.json"), str)


def download_model(model_id: str) -> None:
    """Fetch the model into the local HF cache using the §4.11 allow-list."""
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
