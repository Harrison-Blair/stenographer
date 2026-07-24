# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import concurrent.futures

import numpy as np
import pytest
from huggingface_hub import try_to_load_from_cache

from stenographer.asr import Model, TranscriptionResult, Worker
from stenographer.config import AsrConfig

MODEL = "Systran/faster-whisper-large-v3"

_cached = try_to_load_from_cache(repo_id=MODEL, filename="config.json")
if not (isinstance(_cached, str) and bool(_cached)):
    pytest.skip(
        "ASR model not downloaded; run scripts/download_model.py",
        allow_module_level=True,
    )


@pytest.fixture(scope="session")
def model() -> Model:
    print("loading model (~5 s)...", flush=True)
    return Model(
        AsrConfig(
            model=MODEL,
            language="en",
            beam_size=1,
            compute_type="int8",
            silence_threshold=0.6,
            vad_filter=True,
            max_new_tokens=128,
            mode="eager",
            idle_unload_seconds=0,
            hotwords=None,
            initial_prompt=None,
        )
    )


def test_transcribe_silence(model: Model) -> None:
    samples = np.zeros(16000, dtype=np.float32)
    result = model.transcribe(samples, "en", 1)
    assert isinstance(result, TranscriptionResult)
    assert isinstance(result.text, str)
    assert result.duration_seconds >= 0.0


def test_transcribe_sine_is_rejected_as_non_speech(model: Model) -> None:
    sample_rate = 16000
    t = np.arange(sample_rate, dtype=np.float32) / sample_rate
    samples = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    result = model.transcribe(samples, "en", 1)
    assert isinstance(result, TranscriptionResult)
    assert result.text == ""


def test_transcribe_empty(model: Model) -> None:
    samples = np.zeros(0, dtype=np.float32)
    result = model.transcribe(samples, "en", 1)
    assert isinstance(result, TranscriptionResult)


def test_worker(model: Model) -> None:
    worker = Worker(model)
    worker.start()
    try:
        futures = [worker.submit(np.zeros(16000, dtype=np.float32)) for _ in range(3)]
        _done, not_done = concurrent.futures.wait(futures, timeout=120.0)
        assert not not_done, f"{len(not_done)} futures did not complete in time"
        for fut in futures:
            result = fut.result(timeout=5.0)
            assert isinstance(result, TranscriptionResult)
    finally:
        worker.stop(timeout=30.0)
    assert worker.is_running is False
