# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure sherpa-onnx and faster-whisper CPU costs on labelled WAV files."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np
import soundfile as sf

_RUNS = 20
_SAMPLE_RATE = 16_000
_DURATIONS = (2, 5, 15)
_THRESHOLDS = tuple(round(0.3 + index * 0.05, 2) for index in range(9))


def _audio(path: Path) -> np.ndarray:
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if sample_rate != _SAMPLE_RATE:
        raise ValueError(f"{path} has sample rate {sample_rate}; expected {_SAMPLE_RATE} Hz")
    return np.ascontiguousarray(samples[:, 0])


def _phrase(samples: np.ndarray, seconds: int) -> np.ndarray:
    required = seconds * _SAMPLE_RATE
    if len(samples) >= required:
        return np.ascontiguousarray(samples[:required])
    repeats = (required + len(samples) - 1) // len(samples)
    return np.ascontiguousarray(np.tile(samples, repeats)[:required])


def _load_vad(sherpa_onnx, model_path: Path, *, threads: int):
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(model_path)
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.min_silence_duration = 0.6
    config.silero_vad.max_speech_duration = 25
    config.sample_rate = _SAMPLE_RATE
    config.num_threads = threads
    config.provider = "cpu"
    if not config.validate():
        raise ValueError(f"Invalid Silero VAD model: {model_path}")
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=120)


def _vad_segments(vad, samples: np.ndarray) -> list[dict[str, float]]:
    window_size = 512
    for offset in range(0, len(samples), window_size):
        vad.accept_waveform(samples[offset : offset + window_size])
    vad.flush()
    segments = []
    while not vad.empty():
        segment = vad.front
        start = float(segment.start) / _SAMPLE_RATE
        end = start + len(segment.samples) / _SAMPLE_RATE
        segments.append(
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(end - start, 3),
            }
        )
        vad.pop()
    return segments


def _embedding(extractor, samples: np.ndarray) -> np.ndarray:
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=_SAMPLE_RATE, waveform=samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise ValueError(
            f"Speaker embedding model rejected a {len(samples) / _SAMPLE_RATE:.1f}s phrase"
        )
    return np.asarray(extractor.compute(stream), dtype=np.float32)


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def _cluster(embeddings: list[tuple[str, np.ndarray]], threshold: float) -> dict[str, int]:
    means: list[np.ndarray] = []
    counts: list[int] = []
    members: list[list[str]] = []
    for label, embedding in embeddings:
        if not means:
            means.append(embedding.copy())
            counts.append(1)
            members.append([label])
            continue
        scores = [_cosine(embedding, mean) for mean in means]
        best = int(np.argmax(scores))
        if scores[best] >= threshold:
            members[best].append(label)
            counts[best] += 1
            means[best] += (embedding - means[best]) / counts[best]
        else:
            means.append(embedding.copy())
            counts.append(1)
            members.append([label])

    labels = {label for label, _ in embeddings}
    over_split = sum(max(0, sum(label in member for member in members) - 1) for label in labels)
    merged = sum(max(0, len(set(member)) - 1) for member in members)
    return {
        "cluster_count": len(members),
        "over_split_count": over_split,
        "merge_count": merged,
    }


def _labeled_audio(value: str) -> tuple[str, Path]:
    label, separator, filename = value.partition("=")
    if not separator or not label or not filename:
        raise argparse.ArgumentTypeError("use SPEAKER=PATH for each labelled WAV")
    return label, Path(filename)


def _default_models() -> tuple[Path, str, str, int]:
    from huggingface_hub import try_to_load_from_cache

    from stenographer.lib.config.models import Config
    from stenographer.lib.live.models import LIVE_MODELS
    from stenographer.lib.platform import current_platform

    data_dir = current_platform().data_dir(os.environ, Path.home())
    model_dir = data_dir / "models" / "live"
    for model in LIVE_MODELS:
        path = model_dir / model.filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing {path}; run `stenographer model download --live` first"
            )

    config = Config.defaults()
    cached_config = try_to_load_from_cache(config.asr.model, "config.json")
    if not isinstance(cached_config, str):
        raise FileNotFoundError(
            f"The configured ASR model {config.asr.model!r} is not cached; "
            "run `stenographer model download --asr` first"
        )
    physical_cores = current_platform().physical_core_count() or os.cpu_count() or 1
    whisper_threads = (
        min(8, physical_cores) if config.asr.cpu_threads == 0 else config.asr.cpu_threads
    )
    return model_dir, str(Path(cached_config).parent), config.asr.compute_type, whisper_threads


def run_bench(audio_files: list[tuple[str, Path]], turn_sample: Path) -> dict:
    import psutil
    import sherpa_onnx
    from faster_whisper import WhisperModel

    from stenographer.lib.live.models import LIVE_MODELS

    model_dir, whisper_path, compute_type, whisper_threads = _default_models()
    vad_path = model_dir / LIVE_MODELS[0].filename
    speaker_path = model_dir / LIVE_MODELS[1].filename
    labelled_samples = [(label, path, _audio(path)) for label, path in audio_files]
    turn_samples = _audio(turn_sample)
    combined = np.concatenate([samples for _, _, samples in labelled_samples])

    vad = _load_vad(sherpa_onnx, vad_path, threads=1)
    started = time.perf_counter()
    vad_cuts = _vad_segments(vad, turn_samples)
    vad_elapsed = time.perf_counter() - started

    speaker_embeddings: list[tuple[str, np.ndarray]] = []
    for label, _, samples in labelled_samples:
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(speaker_path), num_threads=1, debug=False, provider="cpu"
            )
        )
        speaker_embeddings.append((label, _embedding(extractor, samples)))

    clustering = []
    for threshold in _THRESHOLDS:
        result = _cluster(speaker_embeddings, threshold)
        clustering.append({"threshold": threshold, **result})
    chosen = min(
        clustering,
        key=lambda result: (
            result["over_split_count"] + result["merge_count"],
            abs(result["threshold"] - 0.5),
            result["threshold"],
        ),
    )

    embedding_times = {}
    for threads in (1, 2, 4):
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(speaker_path), num_threads=threads, debug=False, provider="cpu"
            )
        )
        per_duration = {}
        for seconds in _DURATIONS:
            phrase = _phrase(combined, seconds)
            _embedding(extractor, phrase)
            timings = []
            for _ in range(_RUNS):
                started = time.perf_counter()
                _embedding(extractor, phrase)
                timings.append((time.perf_counter() - started) * 1000)
            per_duration[str(seconds)] = {
                "runs": _RUNS,
                "median_ms": round(statistics.median(timings), 3),
                "p95_ms": round(float(np.percentile(timings, 95)), 3),
            }
        embedding_times[str(threads)] = per_duration

    whisper = WhisperModel(
        whisper_path,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=whisper_threads,
        num_workers=1,
    )
    whisper_times = {}
    warmup = _phrase(turn_samples, 15)
    list(whisper.transcribe(warmup, language="en", beam_size=1, vad_filter=False)[0])
    for seconds in _DURATIONS:
        phrase = _phrase(turn_samples, seconds)
        started = time.perf_counter()
        list(whisper.transcribe(phrase, language="en", beam_size=1, vad_filter=False)[0])
        elapsed = time.perf_counter() - started
        whisper_times[str(seconds)] = {
            "decode_seconds": round(elapsed, 3),
            "real_time_factor": round(elapsed / seconds, 4),
        }

    return {
        "cpu": {
            "processor": platform.processor() or platform.machine(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_threads": os.cpu_count(),
        },
        "audio": {
            "labelled_files": [
                {"speaker": label, "path": str(path)} for label, path, _ in labelled_samples
            ],
            "turn_sample": str(turn_sample),
            "sample_rate": _SAMPLE_RATE,
        },
        "vad": {
            "threads": 1,
            "duration_seconds": round(len(turn_samples) / _SAMPLE_RATE, 3),
            "processing_seconds": round(vad_elapsed, 3),
            "real_time_factor": round(vad_elapsed / (len(turn_samples) / _SAMPLE_RATE), 5),
            "phrase_cuts": vad_cuts,
        },
        "speaker_clustering": {
            "method": "D7 online cosine matching to running mean embeddings",
            "expected_speakers": len({label for label, _, _ in labelled_samples}),
            "thresholds": clustering,
            "chosen_threshold": chosen["threshold"],
        },
        "embedding": {
            "phrase_durations_seconds": list(_DURATIONS),
            "thread_counts": embedding_times,
        },
        "whisper": {
            "model": whisper_path,
            "compute_type": compute_type,
            "cpu_threads": whisper_threads,
            "phrases": whisper_times,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio",
        action="append",
        type=_labeled_audio,
        required=True,
        metavar="SPEAKER=PATH",
        help="A 16 kHz WAV containing one labelled speaker; repeat for each file.",
    )
    parser.add_argument(
        "--turn-sample",
        type=Path,
        required=True,
        help="A 16 kHz multi-speaker WAV for VAD timing and phrase cuts.",
    )
    args = parser.parse_args()
    if len({label for label, _ in args.audio}) < 2:
        parser.error("--audio must include at least two distinct speaker labels")
    result = run_bench(args.audio, args.turn_sample)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
