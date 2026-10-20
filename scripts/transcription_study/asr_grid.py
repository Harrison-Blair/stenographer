# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU-only model, decoding-setting, and context comparison grid."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from transcription_study.context import build_prompt, recording_groups
from transcription_study.scoring import score

MODEL_REPOSITORIES = {
    "medium.en": "Systran/faster-whisper-medium.en",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo-ct2": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "base.en": "Systran/faster-whisper-base.en",
}
CONTEXT_MODES = ("off", "reference", "decoded")
_REPEATED_PHRASE = re.compile(r"(?=(\band\s+more\b[\s,.;:!?—-]+\band\s+more\b))", re.IGNORECASE)
_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class GridSetting:
    beam_size: int
    hotwords: bool
    context: str
    compute_type: str = "int8"

    @property
    def id(self) -> str:
        hotwords = "on" if self.hotwords else "off"
        return f"beam{self.beam_size}-hotwords-{hotwords}-context-{self.context}"


def grid_settings() -> list[GridSetting]:
    """Return the required beam/hotword/context grid using CPU int8 only."""
    return [
        GridSetting(beam_size=beam_size, hotwords=hotwords, context=context)
        for beam_size in (1, 5)
        for hotwords in (False, True)
        for context in CONTEXT_MODES
    ]


def repeated_phrase_hallucinations(text: str) -> int:
    """Count adjacent occurrences of the known repeated phrase."""
    return len(_REPEATED_PHRASE.findall(text))


class PeakRSS:
    """Sample process RSS during one setting, including its loaded model."""

    def __init__(self, interval: float = 0.05) -> None:
        import psutil

        self._process = psutil.Process()
        self._interval = interval
        self.peak_bytes = self._process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join()
        self._sample_once()

    def _sample_once(self) -> None:
        self.peak_bytes = max(self.peak_bytes, self._process.memory_info().rss)

    def _sample(self) -> None:
        while not self._stop.wait(self._interval):
            self._sample_once()


def percentile(values: list[float], fraction: float) -> float | None:
    """Linearly interpolated percentile."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _load_public_clips(
    manifest: dict, split: str, limit: int, digest
) -> tuple[list[list[dict]], dict]:
    """Load and validate one fixed split without printing reference text."""
    import soundfile as sf

    from stenographer.lib.audio.constants import SAMPLE_RATE
    from stenographer.lib.audio.resample import _resample_poly
    from transcription_study.audio import transform
    from transcription_study.profiles import select_clips

    clips = select_clips(manifest, split, limit)
    loaded = {}
    for clip in clips:
        audio_path = Path(clip["audio_path"])
        reference_path = Path(clip["reference_path"])
        if digest(audio_path.read_bytes()) != clip["sha256"]:
            raise ValueError("audio_checksum_mismatch")
        reference_bytes = reference_path.read_bytes()
        if digest(reference_bytes) != clip["reference_sha256"]:
            raise ValueError("reference_checksum_mismatch")
        reference = reference_bytes.decode("utf-8")
        samples, rate = sf.read(audio_path, dtype="float32", always_2d=False)
        samples = transform(samples, rate, channel="first")
        samples = _resample_poly(samples, rate, SAMPLE_RATE)
        loaded[clip["id"]] = {"samples": samples, "reference": reference}
    return recording_groups(clips), loaded


def _dictation_clip(groups: list[list[dict]]) -> tuple[dict, list[dict]]:
    candidates = []
    for group in groups:
        for index, clip in enumerate(group):
            if index and 4 <= clip["duration_seconds"] <= 12:
                previous = group[max(0, index - 3) : index]
                candidates.append((abs(clip["duration_seconds"] - 7), clip, previous))
    if not candidates:
        raise ValueError("no_dictation_clip_with_prior_context")
    _, clip, previous = min(candidates, key=lambda item: (item[0], item[1]["id"]))
    return clip, previous


def _setting_fingerprint(metadata: dict, setting: GridSetting, digest) -> str:
    payload = {**metadata, "grid_setting": asdict(setting), "setting_id": setting.id}
    return digest(json.dumps(payload, sort_keys=True, allow_nan=False).encode())


def _decode_clip(
    clip: dict,
    samples: np.ndarray,
    reference: str,
    decoder,
    cfg,
    setting: GridSetting,
    prompt: str | None,
    source_ids: list[str],
    hotwords: str | None,
) -> tuple[dict, str]:
    from stenographer.lib.audio.gate import speech_gate_stats
    from transcription_study.records import Profile

    if clip["id"] in source_ids:
        raise ValueError("target_clip_in_context")
    audio_seconds = len(samples) / _SAMPLE_RATE
    gate = speech_gate_stats(samples, _SAMPLE_RATE, cfg.audio.min_speech_rms)
    status = "gate_rejected"
    error_type = None
    decode_seconds = 0.0
    hypothesis = ""
    if gate.passed:
        started = time.perf_counter()
        try:
            result = decoder.transcribe(
                samples,
                Profile(setting.id),
                beam_size=setting.beam_size,
                hotwords=hotwords if setting.hotwords else None,
                initial_prompt=prompt,
            )
            hypothesis = result["texts"]["formatted"] or ""
            status = result["status"]
            error_type = result.get("error_type")
            decode_seconds = result["decode_seconds"]
        except Exception as exc:
            status = "decode_error"
            error_type = type(exc).__name__
            decode_seconds = time.perf_counter() - started
    return (
        {
            "kind": "wer",
            "version": 1,
            "clip_id": clip["id"],
            "split": clip["split"],
            "corpus": clip["corpus"],
            "group": clip["group"],
            "recording": clip["meeting"] + ":" + clip["capture"]
            if clip.get("meeting") and clip.get("capture")
            else clip.get("archive_member", clip["id"]),
            "setting": setting.id,
            "model": clip.get("_model"),
            "beam_size": setting.beam_size,
            "compute_type": setting.compute_type,
            "hotwords": setting.hotwords,
            "context": setting.context,
            "prompt_source_clip_ids": source_ids,
            "own_reference_in_prompt": clip["id"] in source_ids,
            "gate": {"passed": gate.passed, "peak_rms": gate.peak_rms},
            "audio_seconds": audio_seconds,
            "decode_seconds": decode_seconds,
            "real_time_factor": decode_seconds / audio_seconds if audio_seconds else None,
            "status": status,
            "error_type": error_type,
            "scores": score(reference, hypothesis),
            "backend": decoder.backend,
        },
        hypothesis,
    )


def _write_row(stream, row: dict) -> None:
    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    stream.flush()


def _repair_incomplete_final_row(path: Path) -> None:
    if not path.exists():
        return
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        last = data.rfind(b"\n")
        try:
            json.loads(data[last + 1 :])
        except json.JSONDecodeError:
            path.write_bytes(data[: last + 1])
        else:
            with path.open("ab") as stream:
                stream.write(b"\n")


def run_public_grid(
    args,
    *,
    run_metadata,
    override_config,
    fingerprint,
    completed_rows,
    digest,
) -> int:
    """Run WER and repeated dictation latency for cached models only."""
    from datetime import UTC, datetime

    from stenographer.lib.config.models import Config
    from stenographer.lib.config.paths import resolve_config_path
    from transcription_study.decode import Decoder
    from transcription_study.records import Profile

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    logging.disable(logging.CRITICAL)

    config_path = args.config or resolve_config_path(create_parent=False)
    base_cfg = Config.load(config_path) if config_path.is_file() else Config.defaults()
    hotwords = base_cfg.asr.hotwords
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("unsupported_manifest_version")
    groups, loaded = _load_public_clips(manifest, "dev", args.grid_limit, digest)
    references = {clip["id"]: loaded[clip["id"]]["reference"] for group in groups for clip in group}
    dictation_clip, dictation_previous = _dictation_clip(groups)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = Path(str(output) + ".meta.json")
    metadata_index = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
    completed = completed_rows(output) if args.resume else set()
    setting_list = grid_settings()
    models = [name.strip() for name in args.models.split(",") if name.strip()]
    if not models or any(name not in MODEL_REPOSITORIES for name in models):
        raise ValueError("unknown_model_alias")
    _repair_incomplete_final_row(output)

    from stenographer.lib.audio.constants import SAMPLE_RATE

    latency_samples = loaded[dictation_clip["id"]]["samples"]
    expected_clip_ids = [clip["id"] for group in groups for clip in group]
    default_latency_id = "__dictation_latency__"
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
            base_meta = run_metadata(
                args.manifest, cfg, [Profile(setting.id) for setting in setting_list], False
            )
            base_meta["backend"] = decoder.backend
            base_meta["model_alias"] = model_alias
            for setting in setting_list:
                setting_fingerprint = _setting_fingerprint(base_meta, setting, digest)
                metadata_index[setting_fingerprint] = {
                    **base_meta,
                    "grid_setting": asdict(setting),
                    "active_setting": setting.id,
                    "started_utc": datetime.now(UTC).isoformat(),
                    "context_policy": "up to 3 immediately prior clips; reset by recording",
                    "latency_clip_id": dictation_clip["id"],
                    "latency_repeats": args.latency_repeats,
                }
                sidecar_path.write_text(json.dumps(metadata_index, indent=2, sort_keys=True) + "\n")
                wer_keys = {(setting_fingerprint, clip_id, "dev") for clip_id in expected_clip_ids}
                latency_key = (setting_fingerprint, default_latency_id, "dev")
                if args.resume and wer_keys.issubset(completed) and latency_key in completed:
                    continue
                decoded = {}
                with PeakRSS() as rss:
                    for group in groups:
                        for index, clip in enumerate(group):
                            prior = group[max(0, index - 3) : index]
                            prompt, source_ids = build_prompt(
                                clip,
                                prior,
                                references=references,
                                decoded=decoded,
                                mode=setting.context,
                            )
                            data = loaded[clip["id"]]
                            row, hypothesis = _decode_clip(
                                clip,
                                data["samples"],
                                data["reference"],
                                decoder,
                                cfg,
                                setting,
                                prompt,
                                source_ids,
                                hotwords,
                            )
                            row.update(
                                model=model_alias,
                                model_repository=model_repo,
                                fingerprint=setting_fingerprint,
                            )
                            decoded[clip["id"]] = hypothesis
                            if clip["id"] in source_ids or row["own_reference_in_prompt"]:
                                raise ValueError("prompt_leakage")
                            if (setting_fingerprint, clip["id"], "dev") not in completed:
                                _write_row(stream, row)
                                completed.add((setting_fingerprint, clip["id"], "dev"))
                    prompt, source_ids = build_prompt(
                        dictation_clip,
                        dictation_previous,
                        references=references,
                        decoded=decoded,
                        mode=setting.context,
                    )
                    options = {
                        "beam_size": setting.beam_size,
                        "hotwords": hotwords if setting.hotwords else None,
                        "initial_prompt": prompt,
                    }
                    if latency_key not in completed:
                        times = []
                        error_type = None
                        try:
                            decoder.transcribe(latency_samples, Profile(setting.id), **options)
                            for _ in range(args.latency_repeats):
                                started = time.perf_counter()
                                decoder.transcribe(latency_samples, Profile(setting.id), **options)
                                times.append(time.perf_counter() - started)
                        except Exception as exc:
                            error_type = type(exc).__name__
                        enough_repeats = len(times) >= args.latency_repeats
                        latency_row = {
                            "kind": "dictation_latency",
                            "model": model_alias,
                            "model_repository": model_repo,
                            "setting": setting.id,
                            "beam_size": setting.beam_size,
                            "compute_type": setting.compute_type,
                            "hotwords": setting.hotwords,
                            "context": setting.context,
                            "latency_clip_id": dictation_clip["id"],
                            "latency_clip_seconds": len(latency_samples) / SAMPLE_RATE,
                            "latency_repeats": len(times),
                            "latency_seconds": times,
                            "latency_median_seconds": statistics.median(times)
                            if enough_repeats
                            else None,
                            "latency_p90_seconds": percentile(times, 0.9)
                            if enough_repeats
                            else None,
                            "latency_rtf": statistics.median(times)
                            / (len(latency_samples) / SAMPLE_RATE)
                            if enough_repeats
                            else None,
                            "status": "ok" if enough_repeats else "decode_error",
                            "error_type": error_type,
                            "prompt_source_clip_ids": source_ids,
                            "own_reference_in_prompt": dictation_clip["id"] in source_ids,
                            "rss_peak_bytes": rss.peak_bytes,
                            "backend": decoder.backend,
                            "fingerprint": setting_fingerprint,
                            "clip_id": default_latency_id,
                            "split": "dev",
                        }
                        _write_row(stream, latency_row)
                        completed.add(latency_key)
                print(
                    json.dumps(
                        {
                            "kind": "setting_complete",
                            "model": model_alias,
                            "setting": setting.id,
                            "clips": len(expected_clip_ids),
                        }
                    ),
                    flush=True,
                )
            decoder.close()
    sidecar_path.write_text(json.dumps(metadata_index, indent=2, sort_keys=True) + "\n")
    summary_path = output.with_suffix(".summary.json")
    summary = summarize_public_grid(output, models, setting_list, args.grid_limit)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"kind": "grid_complete", "summary": str(summary_path)}))
    return 0


def summarize_public_grid(
    output: Path, models: list[str], settings: list[GridSetting], clip_count: int
) -> dict:
    """Aggregate numeric rows for one model-setting table."""
    rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    wer_rows = [row for row in rows if row.get("kind") == "wer"]
    latency_rows = [row for row in rows if row.get("kind") == "dictation_latency"]
    results = []
    for model in models:
        for setting in settings:
            matching = [
                row for row in wer_rows if row["model"] == model and row["setting"] == setting.id
            ]
            if not matching:
                continue
            totals = {
                key: sum(row["scores"][key] for row in matching) for key in ("S", "D", "I", "N")
            }
            words = totals["N"]
            errors = totals["S"] + totals["D"] + totals["I"]
            latency = next(
                (
                    row
                    for row in latency_rows
                    if row["model"] == model and row["setting"] == setting.id
                ),
                None,
            )
            results.append(
                {
                    "model": model,
                    "model_repository": matching[0]["model_repository"],
                    "setting": setting.id,
                    "beam_size": setting.beam_size,
                    "compute_type": setting.compute_type,
                    "hotwords": setting.hotwords,
                    "context": setting.context,
                    "clips": len(matching),
                    "expected_clips": clip_count,
                    "complete": len(matching) == clip_count and latency is not None,
                    **totals,
                    "errors": errors,
                    "wer": errors / words if words else None,
                    "latency_median_seconds": latency["latency_median_seconds"]
                    if latency
                    else None,
                    "latency_p90_seconds": latency["latency_p90_seconds"] if latency else None,
                    "latency_rtf": latency["latency_rtf"] if latency else None,
                    "rss_peak_bytes": latency["rss_peak_bytes"] if latency else None,
                    "extra_latency_vs_default_seconds": None,
                    "own_reference_prompt_rows": sum(
                        bool(row["own_reference_in_prompt"]) for row in matching
                    ),
                    "statuses": {
                        status: sum(row["status"] == status for row in matching)
                        for status in sorted({row["status"] for row in matching})
                    },
                }
            )
    baseline_id = "beam1-hotwords-on-context-off"
    baseline = next(
        (
            row["latency_median_seconds"]
            for row in results
            if row["model"] == "medium.en"
            and row["setting"] == baseline_id
            and row["latency_median_seconds"] is not None
        ),
        None,
    )
    for row in results:
        if baseline is not None and row["latency_median_seconds"] is not None:
            row["extra_latency_vs_default_seconds"] = row["latency_median_seconds"] - baseline
    return {
        "status": "complete" if results and all(row["complete"] for row in results) else "partial",
        "models_requested": models,
        "settings_per_model": len(settings),
        "wer_split": "dev",
        "latency_baseline": {
            "model": "medium.en",
            "compute_type": "int8",
            "beam_size": 1,
            "hotwords": "configured default on",
            "context": "off",
            "median_seconds": baseline,
        },
        "name_entity_errors": "not annotated in this corpus",
        "results": results,
    }
