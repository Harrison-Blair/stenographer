# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure cached ASR settings on fixed, no-reference live-VAD excerpts."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from transcription_study.asr_grid import (
    MODEL_REPOSITORIES,
    PeakRSS,
    grid_settings,
    percentile,
    repeated_phrase_hallucinations,
)
from transcription_study.context import build_prompt

_SAMPLE_RATE = 16000
_EXCERPT_COUNT = 20
_WINDOW_SECONDS = 60
_STABILITY_SECONDS = 120
_MAX_STABILITY_WAIT_SECONDS = 600
_SAMPLE_PATH = Path("/home/penguin/source/hive/.hive/tmp/reports/stenographer-hub/bench-samples.md")
_SUSPECT = re.compile(r"\b(?:kadian|roic|waudio)\b", re.IGNORECASE)
_REPEAT_PATTERN = re.compile(r"\band\s+more\b[\s,.;:!?—-]+\band\s+more\b", re.IGNORECASE)


def wait_until_stable(
    path: Path,
    *,
    stable_seconds: float = _STABILITY_SECONDS,
    max_wait_seconds: float = _MAX_STABILITY_WAIT_SECONDS,
) -> int | None:
    """Return the size after two stable minutes, or None after ten minutes."""
    if not path.is_file():
        raise FileNotFoundError("long_recording_missing")
    started = time.monotonic()
    last_change = started
    previous_size = path.stat().st_size
    while True:
        elapsed = time.monotonic() - started
        remaining = max_wait_seconds - elapsed
        if remaining <= 0:
            return None
        time.sleep(min(stable_seconds - (time.monotonic() - last_change), remaining))
        size = path.stat().st_size
        if size != previous_size:
            previous_size = size
            last_change = time.monotonic()
            continue
        if time.monotonic() - last_change >= stable_seconds:
            return size


def candidate_snippets(text: str) -> list[str]:
    """Return short windows around only the known suspicious output patterns."""
    matches = list(_SUSPECT.finditer(text)) + list(_REPEAT_PATTERN.finditer(text))
    snippets = []
    for match in sorted(matches, key=lambda item: item.start()):
        start = max(0, match.start() - 70)
        end = min(len(text), match.end() + 70)
        snippet = " ".join(text[start:end].split())
        if snippet and snippet not in snippets:
            snippets.append(snippet)
    return snippets


def _write_sample(path: Path, model: str, setting: str, excerpt: int, snippet: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        if path.stat().st_size == 0:
            stream.write("# Long-recording ASR sample candidates (uncommitted)\n\n")
        stream.write(f"- {model} / {setting} / excerpt {excerpt}: {snippet}\n")


def _vad_model_path() -> Path:
    from stenographer.lib.live.models import LIVE_MODELS
    from stenographer.lib.platform import current_platform

    root = current_platform().data_dir(os.environ, Path.home()) / "models" / "live"
    path = root / LIVE_MODELS[0].filename
    if not path.is_file():
        raise FileNotFoundError("cached_live_vad_missing")
    return path


def _load_excerpts(path: Path, expected_size: int) -> tuple[list[dict], dict]:
    import soundfile as sf

    from stenographer.lib.audio.resample import _resample_poly
    from stenographer.lib.live.phrase_segmenter import PhraseSegmenter

    if path.stat().st_size != expected_size:
        raise ValueError("recording_changed_after_stability_check")
    info = sf.info(path)
    if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0:
        raise ValueError("invalid_long_recording")
    duration = info.frames / info.samplerate
    vad_path = _vad_model_path()
    excerpts = []
    segmenter = PhraseSegmenter("system", vad_path, max_phrase_seconds=25)
    block_frames = round(_WINDOW_SECONDS * info.samplerate)
    with sf.SoundFile(path) as source:
        for frame_start in range(0, info.frames, block_frames):
            frame_count = min(block_frames, info.frames - frame_start)
            samples = source.read(frame_count, dtype="float32", always_2d=True)
            mono = np.ascontiguousarray(samples[:, 0])
            mono = _resample_poly(mono, info.samplerate, _SAMPLE_RATE)
            for phrase in segmenter.accept(mono):
                excerpt_samples = np.ascontiguousarray(phrase.samples, dtype=np.float32)
                excerpts.append(
                    {
                        "id": f"excerpt-{len(excerpts) + 1:02d}",
                        "meeting": "long-recording",
                        "capture": "system-audio",
                        "start_seconds": phrase.start,
                        "duration_seconds": len(excerpt_samples) / _SAMPLE_RATE,
                        "samples": excerpt_samples,
                    }
                )
                if len(excerpts) == _EXCERPT_COUNT:
                    break
            if len(excerpts) == _EXCERPT_COUNT:
                break
        if len(excerpts) < _EXCERPT_COUNT:
            for phrase in segmenter.flush():
                excerpt_samples = np.ascontiguousarray(phrase.samples, dtype=np.float32)
                excerpts.append(
                    {
                        "id": f"excerpt-{len(excerpts) + 1:02d}",
                        "meeting": "long-recording",
                        "capture": "system-audio",
                        "start_seconds": phrase.start,
                        "duration_seconds": len(excerpt_samples) / _SAMPLE_RATE,
                        "samples": excerpt_samples,
                    }
                )
                if len(excerpts) == _EXCERPT_COUNT:
                    break
    if path.stat().st_size != expected_size:
        raise ValueError("recording_changed_after_stability_check")
    return excerpts, {
        "file_size_bytes": expected_size,
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "duration_seconds": duration,
        "vad_excerpt_count": len(excerpts),
        "excerpt_selection": "first 20 live-VAD phrases in recording order",
        "vad_model_sha256": _sha256(vad_path),
    }


def _sha256(path: Path) -> str:
    import hashlib

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json_row(stream, row: dict) -> None:
    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    stream.flush()


def run_real_audio_grid(args, *, run_metadata, override_config, digest) -> int:
    """Run identical VAD excerpts through each cached model and applicable setting."""
    from stenographer.lib.config.models import Config
    from stenographer.lib.config.paths import resolve_config_path
    from transcription_study.decode import Decoder
    from transcription_study.records import Profile

    path = args.real_audio
    stable_size = wait_until_stable(path)
    if stable_size is None:
        print(json.dumps({"status": "recording_still_growing"}), flush=True)
        return 2
    excerpts, audio_metadata = _load_excerpts(path, stable_size)
    if not excerpts:
        raise ValueError("no_live_vad_excerpts")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    logging.disable(logging.CRITICAL)
    config_path = args.config or resolve_config_path(create_parent=False)
    base_cfg = Config.load(config_path) if config_path.is_file() else Config.defaults()
    hotwords = base_cfg.asr.hotwords
    models = [name.strip() for name in args.models.split(",") if name.strip()]
    if not models or any(name not in MODEL_REPOSITORIES for name in models):
        raise ValueError("unknown_model_alias")
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = Path(str(output) + ".meta.json")
    metadata_index = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    sample_lines = 0

    with output.open("a", encoding="utf-8") as stream:
        for model_alias in models:
            model_repo = MODEL_REPOSITORIES[model_alias]
            cfg = override_config(
                base_cfg,
                model=model_repo,
                compute_type="int8",
                cpu_threads=args.cpu_threads,
            )
            decoder = Decoder(cfg.asr)
            setting_list = grid_settings()
            base_meta = run_metadata(
                args.manifest, cfg, [Profile(setting.id) for setting in setting_list], False
            )
            base_meta["backend"] = decoder.backend
            base_meta["model_alias"] = model_alias
            for setting in setting_list:
                fingerprint_data = {
                    **base_meta,
                    "real_audio_metadata": audio_metadata,
                    "grid_setting": setting.__dict__,
                }
                fingerprint = digest(
                    json.dumps(fingerprint_data, sort_keys=True, allow_nan=False).encode()
                )
                metadata_index[fingerprint] = {
                    **fingerprint_data,
                    "setting": setting.id,
                    "audio_text_persisted": False,
                    "reference_context": "unavailable: recording has no reference",
                    "started_utc": datetime.now(UTC).isoformat(),
                }
                metadata_path.write_text(
                    json.dumps(metadata_index, indent=2, sort_keys=True) + "\n"
                )
                if setting.context == "reference":
                    for index, excerpt in enumerate(excerpts, 1):
                        _write_json_row(
                            stream,
                            {
                                "kind": "real_audio",
                                "model": model_alias,
                                "setting": setting.id,
                                "context": setting.context,
                                "excerpt": index,
                                "audio_seconds": excerpt["duration_seconds"],
                                "status": "not_applicable_no_reference",
                                "fingerprint": fingerprint,
                            },
                        )
                    continue

                decoded = {}
                durations = []
                latencies = []
                repeated_phrases = 0
                with PeakRSS() as rss:
                    for index, excerpt in enumerate(excerpts):
                        prior = excerpts[max(0, index - 3) : index]
                        prompt, source_ids = build_prompt(
                            excerpt,
                            prior,
                            references={},
                            decoded=decoded,
                            mode=setting.context,
                        )
                        if index == 0:
                            with suppress(Exception):
                                decoder.transcribe(
                                    excerpt["samples"],
                                    Profile(setting.id),
                                    beam_size=setting.beam_size,
                                    hotwords=hotwords if setting.hotwords else None,
                                    initial_prompt=prompt,
                                )
                        started = time.perf_counter()
                        status = "ok"
                        error_type = None
                        hypothesis = ""
                        try:
                            result = decoder.transcribe(
                                excerpt["samples"],
                                Profile(setting.id),
                                beam_size=setting.beam_size,
                                hotwords=hotwords if setting.hotwords else None,
                                initial_prompt=prompt,
                            )
                            hypothesis = result["texts"]["formatted"] or ""
                            status = result["status"]
                            error_type = result.get("error_type")
                        except Exception as exc:
                            status = "decode_error"
                            error_type = type(exc).__name__
                        elapsed = time.perf_counter() - started
                        decoded[excerpt["id"]] = hypothesis
                        durations.append(excerpt["duration_seconds"])
                        latencies.append(elapsed)
                        repeated = repeated_phrase_hallucinations(hypothesis)
                        repeated_phrases += repeated
                        for snippet in candidate_snippets(hypothesis):
                            _write_sample(_SAMPLE_PATH, model_alias, setting.id, index + 1, snippet)
                            sample_lines += 1
                        _write_json_row(
                            stream,
                            {
                                "kind": "real_audio",
                                "model": model_alias,
                                "model_repository": model_repo,
                                "setting": setting.id,
                                "beam_size": setting.beam_size,
                                "compute_type": setting.compute_type,
                                "hotwords": setting.hotwords,
                                "context": setting.context,
                                "excerpt": index + 1,
                                "prompt_source_excerpt_ids": source_ids,
                                "audio_seconds": excerpt["duration_seconds"],
                                "decode_seconds": elapsed,
                                "real_time_factor": elapsed / excerpt["duration_seconds"],
                                "repeated_phrase_hallucinations": repeated,
                                "status": status,
                                "error_type": error_type,
                                "fingerprint": fingerprint,
                                "rss_peak_bytes": rss.peak_bytes,
                            },
                        )
                summary = {
                    "kind": "real_audio_summary",
                    "model": model_alias,
                    "setting": setting.id,
                    "context": setting.context,
                    "excerpts": len(excerpts),
                    "median_decode_seconds": percentile(latencies, 0.5),
                    "p90_decode_seconds": percentile(latencies, 0.9),
                    "real_time_factor": sum(latencies) / sum(durations) if durations else None,
                    "rss_peak_bytes": rss.peak_bytes,
                    "repeated_phrase_hallucinations": repeated_phrases,
                    "reference_context_status": "not applicable",
                    "fingerprint": fingerprint,
                    "status": "complete",
                }
                _write_json_row(stream, summary)
                print(
                    json.dumps(
                        {
                            "kind": "real_audio_setting_complete",
                            "model": model_alias,
                            "setting": setting.id,
                            "excerpts": len(excerpts),
                        }
                    ),
                    flush=True,
                )
            decoder.close()

    if not _SAMPLE_PATH.exists():
        _SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SAMPLE_PATH.write_text(
            "# Long-recording ASR sample candidates (uncommitted)\n\n"
            "No outputs matched the known name/word or repeated-phrase patterns.\n",
            encoding="utf-8",
        )
    summary_path = output.with_suffix(".summary.json")
    rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    summary = {
        "status": "complete",
        "audio": audio_metadata,
        "sample_candidate_lines_written": sample_lines,
        "results": [row for row in rows if row.get("kind") == "real_audio_summary"],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"kind": "real_audio_complete", "summary": str(summary_path)}))
    return 0
