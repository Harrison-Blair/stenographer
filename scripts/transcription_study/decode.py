# SPDX-License-Identifier: GPL-3.0-or-later
"""Instrumented offline decoder using production settings and assembly logic."""

from __future__ import annotations

import time

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.transcribe.decode import _assemble, _token_budget
from stenographer.lib.transcribe.format import format_transcript
from stenographer.lib.transcribe.model import (
    _HALLUCINATION_SILENCE_SECONDS,
    _MAX_NEW_TOKENS,
    _VAD_PARAMETERS,
    Model,
)
from stenographer.lib.transcribe.results import SegmentInfo, WordInfo


class Decoder:
    def __init__(self, cfg):
        started = time.monotonic()
        self.model = Model(cfg)
        self.cfg = cfg
        self.load_seconds = time.monotonic() - started
        backend = self.model._impl.model
        self.backend = {
            "device": str(backend.device),
            "compute_type": str(backend.compute_type),
            "cpu_threads": self.model.cpu_threads,
        }

    def transcribe(self, samples, profile):
        started = time.monotonic()
        cfg = self.cfg
        duration = len(samples) / SAMPLE_RATE
        if not len(samples):
            return {
                "texts": {"raw": "", "assembled": "", "formatted": ""},
                "vad_seconds": 0,
                "decode_seconds": 0,
                "segments_raw": 0,
                "segments_kept": 0,
                "status": "ok",
                "error_type": None,
            }
        options = dict(
            language="en",
            beam_size=cfg.beam_size,
            temperature=0.0,
            no_repeat_ngram_size=3,
            vad_filter=cfg.vad_filter,
            vad_parameters={**_VAD_PARAMETERS, **profile.vad},
            no_speech_threshold=cfg.silence_threshold,
            hallucination_silence_threshold=_HALLUCINATION_SILENCE_SECONDS,
            max_new_tokens=_token_budget(_MAX_NEW_TOKENS, duration),
            condition_on_previous_text=False,
            hotwords=cfg.hotwords or None,
            initial_prompt=cfg.initial_prompt or None,
            word_timestamps=True,
        )
        options.update(profile.decode)
        segments_iter, info = self.model._impl.transcribe(samples, **options)
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
        vad_seconds = float(getattr(info, "duration_after_vad", duration))
        result = {
            "texts": {
                "raw": "".join(seg.text for seg in segments).strip(),
                "assembled": "",
                "formatted": "",
            },
            "vad_seconds": vad_seconds,
            "segments_raw": len(segments),
            "segments_kept": 0,
            "status": "ok",
            "error_type": None,
        }
        try:
            assembled = _assemble(
                segments,
                silence_threshold=(
                    cfg.silence_threshold
                    if profile.post_silence_threshold is None
                    else profile.post_silence_threshold
                ),
                audio_seconds=duration,
                vad_seconds=vad_seconds,
            )
            result["segments_kept"] = len(assembled.segments)
            result["texts"]["assembled"] = assembled.text
            result["texts"]["formatted"] = format_transcript(assembled.text)
        except Exception as exc:
            result["status"] = "validation_error"
            result["error_type"] = type(exc).__name__
        result["decode_seconds"] = time.monotonic() - started
        return result

    def close(self):
        self.model.close()
