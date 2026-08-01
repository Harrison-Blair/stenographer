# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from faster_whisper import WhisperModel

if TYPE_CHECKING:
    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)

_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 100,
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 250,
}
_HALLUCINATION_SILENCE_SECONDS = 2.0
_WORDS_PER_VAD_SECOND = 8
_MIN_WORD_LIMIT = 12


class PathologicalOutputError(RuntimeError):
    """The decoder returned structurally invalid or implausibly dense output."""


@dataclass(frozen=True)
class SegmentInfo:
    start: float
    end: float
    text: str
    no_speech_prob: float


@dataclass(frozen=True)
class WordInfo:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: float
    segments: list[SegmentInfo] = field(default_factory=list)


class Model:
    def __init__(self, cfg: AsrConfig) -> None:
        log.info("loading ASR model: id=%s compute_type=%s", cfg.model, cfg.compute_type)
        self._impl = WhisperModel(
            cfg.model,
            device="auto",
            compute_type=cfg.compute_type,
            local_files_only=True,
        )
        self._language = cfg.language
        self._beam_size = cfg.beam_size
        self._hotwords = cfg.hotwords
        self._initial_prompt = cfg.initial_prompt
        self._silence_threshold = cfg.silence_threshold
        self._vad_filter = cfg.vad_filter
        self._max_new_tokens = cfg.max_new_tokens
        log.info("ASR model loaded: %s", cfg.model)

    @property
    def language(self) -> str:
        return self._language

    @property
    def beam_size(self) -> int:
        return self._beam_size

    def transcribe(
        self,
        samples: np.ndarray,
        language: str,
        beam_size: int,
        on_segment: Callable[[SegmentInfo], None] | None = None,
    ) -> TranscriptionResult:
        if samples.size == 0:
            return TranscriptionResult(text="", duration_seconds=0.0, segments=[])
        if samples.ndim == 2 and samples.shape[1] == 1:
            samples = samples.squeeze(-1)
        started = time.monotonic()
        audio_seconds = samples.shape[0] / 16000
        segments_iter, info = self._impl.transcribe(
            samples,
            language=language,
            beam_size=beam_size,
            temperature=0.0,
            no_repeat_ngram_size=3,
            vad_filter=self._vad_filter,
            vad_parameters=_VAD_PARAMETERS,
            no_speech_threshold=self._silence_threshold,
            hallucination_silence_threshold=_HALLUCINATION_SILENCE_SECONDS,
            max_new_tokens=_token_budget(self._max_new_tokens, audio_seconds),
            condition_on_previous_text=False,
            hotwords=self._hotwords,
            initial_prompt=self._initial_prompt,
            word_timestamps=True,
        )
        seg_infos: list[SegmentInfo] = []
        word_timestamps: list[tuple[float, float]] = []
        confidences: list[float] = []
        for seg in segments_iter:
            si = SegmentInfo(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                no_speech_prob=seg.no_speech_prob,
            )
            if on_segment is not None:
                on_segment(si)
            seg_infos.append(si)
            for word in seg.words or ():
                confidences.append(float(word.probability))
                word_timestamps.append((float(word.start), float(word.end)))
        elapsed = time.monotonic() - started
        duration = float(getattr(info, "duration", audio_seconds))
        duration_after_vad = float(getattr(info, "duration_after_vad", duration))
        _validate_output(
            segment_timestamps=[(segment.start, segment.end) for segment in seg_infos],
            word_timestamps=word_timestamps,
            word_count=len(confidences),
            audio_seconds=audio_seconds,
            vad_seconds=duration_after_vad,
        )
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        log.info(
            "asr: decode duration=%.3fs vad_duration=%.3fs decode_time=%.3fs "
            "word_count=%d mean_confidence=%.3f",
            duration,
            duration_after_vad,
            elapsed,
            len(confidences),
            mean_confidence,
        )
        text = "".join(seg.text for seg in seg_infos).strip()
        return TranscriptionResult(
            text=text,
            duration_seconds=duration,
            segments=seg_infos,
        )

    def transcribe_words(
        self,
        samples: np.ndarray,
        *,
        beam_size: int | None = None,
        check_cancel: Callable[[], None] | None = None,
    ) -> list[WordInfo]:
        """Low-level word-timestamped transcription for incremental decoding.

        Unlike :meth:`transcribe` (the batch daemon path, left untouched),
        this requests ``word_timestamps=True``.  *check_cancel* is invoked
        once per decoded segment so an in-flight re-decode can be aborted
        (it should raise to abort).  Returns a flat, time-ordered list of
        words.

        Segments at or above ``asr.silence_threshold`` are dropped, the same
        gate the batch path applies to :class:`SegmentInfo` — without it
        Whisper's silence hallucinations ("Thank you.") reach the cursor.
        """
        if samples.size == 0:
            return []
        if samples.ndim == 2 and samples.shape[1] == 1:
            samples = samples.squeeze(-1)
        started = time.monotonic()
        audio_seconds = samples.shape[0] / 16000
        segments_iter, info = self._impl.transcribe(
            samples,
            language=self._language,
            beam_size=self._beam_size if beam_size is None else beam_size,
            temperature=0.0,
            no_repeat_ngram_size=3,
            vad_filter=self._vad_filter,
            vad_parameters=_VAD_PARAMETERS,
            no_speech_threshold=self._silence_threshold,
            hallucination_silence_threshold=_HALLUCINATION_SILENCE_SECONDS,
            max_new_tokens=_token_budget(self._max_new_tokens, audio_seconds),
            condition_on_previous_text=False,
            hotwords=self._hotwords,
            initial_prompt=self._initial_prompt,
            word_timestamps=True,
        )
        words: list[WordInfo] = []
        dropped = 0
        for seg in segments_iter:
            if check_cancel is not None:
                check_cancel()
            if seg.no_speech_prob >= self._silence_threshold:
                dropped += 1
                continue
            for w in seg.words or ():
                words.append(
                    WordInfo(start=w.start, end=w.end, word=w.word, probability=w.probability)
                )
        if dropped:
            log.info("asr: dropped %d probable-silence segment(s) from word decode", dropped)
        elapsed = time.monotonic() - started
        duration = audio_seconds
        duration_after_vad = float(getattr(info, "duration_after_vad", duration))
        _validate_output(
            segment_timestamps=[],
            word_timestamps=[(word.start, word.end) for word in words],
            word_count=len(words),
            audio_seconds=duration,
            vad_seconds=duration_after_vad,
        )
        mean_confidence = sum(word.probability for word in words) / len(words) if words else 0.0
        log.info(
            "asr: decode duration=%.3fs vad_duration=%.3fs decode_time=%.3fs "
            "word_count=%d mean_confidence=%.3f",
            duration,
            duration_after_vad,
            elapsed,
            len(words),
            mean_confidence,
        )
        return words

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl


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
    """Reject invalid timestamps and decoder-runaway word density.

    Transcript content is deliberately absent from both the exception and log
    messages so pathological output never leaks dictated text into logs.
    """
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
