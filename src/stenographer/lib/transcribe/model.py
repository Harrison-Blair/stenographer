# SPDX-License-Identifier: GPL-3.0-or-later
"""faster-whisper wrapper: fixed anti-hallucination decode stack.

All testable logic lives in the pure helpers so the ``WhisperModel`` call never
needs mocking; faster-whisper is imported inside ``Model.__init__`` so the cache
probe and download helpers stay light."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    import numpy as np

    from stenographer.lib.config.models import AsrConfig

from stenographer.lib.transcribe.decode import _assemble, _token_budget, resolve_cpu_threads
from stenographer.lib.transcribe.results import SegmentInfo, TranscriptionResult, WordInfo

log = logging.getLogger(__name__)


_MAX_NEW_TOKENS = 128


_HALLUCINATION_SILENCE_SECONDS = 2.0


_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 100,
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 250,
}


class Model:
    def __init__(self, cfg: AsrConfig) -> None:
        from faster_whisper import WhisperModel

        from stenographer.lib.platform import current_platform

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
        self.cpu_threads = cpu_threads
        log.info(
            "asr: model_loaded elapsed_ms=%d cpu_threads=%d",
            round((time.monotonic() - started) * 1000),
            cpu_threads,
        )

    @staticmethod
    def _is_silent_input(samples: np.ndarray) -> bool:
        """True when the capture holds no frames, the one input that skips decode. PURE."""
        return samples.size == 0

    @staticmethod
    def _prepare_samples(samples: np.ndarray) -> np.ndarray:
        """Return the 1-D mono buffer the decoder expects, downmixing 2-D captures. PURE.

        Multi-channel input is averaged across channels; a single-channel 2-D
        capture drops its trailing axis. 1-D input is handed back unchanged.
        """
        if samples.ndim == 2:
            return samples.mean(axis=1) if samples.shape[1] > 1 else samples.squeeze(-1)
        return samples

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        started = time.monotonic()
        if self._is_silent_input(samples):
            log.info(
                "asr: decode_complete elapsed_ms=%d audio_frames=0 vad_frames=0 "
                "segments=0 words=0 transcript_chars=0",
                round((time.monotonic() - started) * 1000),
            )
            return TranscriptionResult(text="", duration_seconds=0.0, segments=[], vad_seconds=0.0)
        samples = self._prepare_samples(samples)
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
            "asr: decode_complete elapsed_ms=%d audio_frames=%d vad_frames=%d "
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
