# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from faster_whisper import WhisperModel

if TYPE_CHECKING:
    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentInfo:
    start: float
    end: float
    text: str
    no_speech_prob: float


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
        )
        self._language = cfg.language
        self._beam_size = cfg.beam_size
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
        segments_iter, info = self._impl.transcribe(
            samples,
            language=language,
            beam_size=beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        seg_infos: list[SegmentInfo] = []
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
        text = "".join(seg.text for seg in seg_infos).strip()
        return TranscriptionResult(
            text=text,
            duration_seconds=info.duration,
            segments=seg_infos,
        )

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl
