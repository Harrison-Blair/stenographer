# SPDX-License-Identifier: GPL-3.0-or-later
"""sherpa-onnx wrapper: Underdog Bark 3.0 Pro int8, greedy TDT decode on the CPU.

All testable logic lives in the pure helpers so the recognizer call never needs
mocking; sherpa_onnx is imported inside ``Model.__init__`` so the cache probe and
download helpers stay light."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from stenographer.lib.audio.constants import SAMPLE_RATE

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

    from stenographer.lib.config.models import AsrConfig

from stenographer.lib.transcribe.decode import (
    _assemble,
    decode_segments,
    pad_samples,
    resolve_cpu_threads,
    words_from_tokens,
)
from stenographer.lib.transcribe.results import TranscriptionResult

log = logging.getLogger(__name__)


#: Leading digital silence the Pro model card asks for before each decode.
_PAD_SECONDS = 0.25


class Model:
    def __init__(
        self,
        cfg: AsrConfig,
        *,
        recognizer: object | None = None,
        data_dir: Path | None = None,
    ) -> None:
        from stenographer.lib.platform import current_platform

        # An explicit thread count short-circuits the host probe entirely.
        cpu_threads = cfg.cpu_threads or resolve_cpu_threads(
            0, current_platform().physical_core_count()
        )
        started = time.monotonic()
        self._impl = recognizer if recognizer is not None else self._load(cpu_threads, data_dir)
        self.cpu_threads = cpu_threads
        log.info(
            "asr: model_loaded elapsed_ms=%d cpu_threads=%d",
            round((time.monotonic() - started) * 1000),
            cpu_threads,
        )

    @staticmethod
    def _load(cpu_threads: int, data_dir: Path | None) -> object:
        import os
        from pathlib import Path

        from stenographer.lib.platform import current_platform
        from stenographer.lib.transcribe import bark_download

        if data_dir is None:
            data_dir = current_platform().data_dir(os.environ, Path.home())
        if not bark_download.is_model_cached(data_dir):
            raise FileNotFoundError(
                f"ASR model not installed at {bark_download.model_dir(data_dir)}; "
                "run `stenographer model download --asr`"
            )
        import sherpa_onnx

        root = bark_download.model_dir(data_dir)
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(root / "encoder.int8.onnx"),
            decoder=str(root / "decoder.int8.onnx"),
            joiner=str(root / "joiner.int8.onnx"),
            tokens=str(root / "tokens.txt"),
            num_threads=cpu_threads,
            sample_rate=SAMPLE_RATE,
            decoding_method="greedy_search",
            provider="cpu",
            model_type="nemo_transducer",
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
        audio_seconds = samples.shape[0] / SAMPLE_RATE
        stream = self._impl.create_stream()
        stream.accept_waveform(SAMPLE_RATE, pad_samples(samples, _PAD_SECONDS))
        self._impl.decode_stream(stream)
        decoded = stream.result
        words = words_from_tokens(
            list(decoded.tokens),
            list(decoded.timestamps),
            list(decoded.durations),
            list(decoded.ys_log_probs),
            offset=_PAD_SECONDS,
        )
        # The input is already speech only (the dictation VAD or a live phrase),
        # so the VAD duration is the whole input.
        result = _assemble(
            decode_segments(decoded.text, words),
            audio_seconds=audio_seconds,
            vad_seconds=audio_seconds,
        )
        log.info(
            "asr: decode_complete elapsed_ms=%d audio_frames=%d vad_frames=%d "
            "segments=%d words=%d transcript_chars=%d",
            round((time.monotonic() - started) * 1000),
            samples.shape[0],
            samples.shape[0],
            len(result.segments),
            sum(len(s.words) for s in result.segments),
            len(result.text),
        )
        return result

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl
