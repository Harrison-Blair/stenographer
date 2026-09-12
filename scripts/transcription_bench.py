# SPDX-License-Identifier: GPL-3.0-or-later
"""Checkpointed offline ASR experiment runner; never records transcript text.

Run with .venv/bin/python scripts/transcription_bench.py --help. Public audio and
reference files must already exist. This command neither downloads nor records.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import random
import subprocess
import sys
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from transcription_study.profiles import PROFILES, select_clips
from transcription_study.scoring import score

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.gate import speech_gate_stats
from stenographer.lib.audio.resample import _resample_poly
from stenographer.lib.config.models import Config
from stenographer.lib.config.paths import resolve_config_path


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def override_config(cfg: Config, *, model=None, compute_type=None, cpu_threads=None) -> Config:
    """Apply benchmark-only ASR overrides to a new immutable configuration."""
    overrides = {
        key: value
        for key, value in {
            "model": model,
            "compute_type": compute_type,
            "cpu_threads": cpu_threads,
        }.items()
        if value is not None
    }
    return replace(cfg, asr=replace(cfg.asr, **overrides))


def run_metadata(manifest_path: Path, cfg: Config, profiles: list, refine: bool) -> dict:
    import psutil
    from faster_whisper.utils import download_model

    root = Path(__file__).resolve().parents[1]
    executed_modules = ("audio", "decode", "profiles", "records", "scoring", "refinement")
    sources = [
        Path(__file__),
        *(root / "scripts/transcription_study" / f"{name}.py" for name in executed_modules),
        *sorted((root / "src/stenographer/lib").rglob("*.py")),
    ]
    versions = {}
    for package in (
        "stenographer",
        "numpy",
        "faster-whisper",
        "ctranslate2",
        "soundfile",
        "onnxruntime",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    asr = asdict(cfg.asr)
    for key in ("hotwords", "initial_prompt"):
        asr[key] = {"present": bool(asr[key]), "sha256": digest((asr[key] or "").encode())}
    # Host and input-device names are unnecessary for reproducibility of file input.
    settings = {
        "asr": asr,
        "min_speech_rms": cfg.audio.min_speech_rms,
        "refine_enabled_for_run": refine,
        "refine_config_sha256": digest(json.dumps(asdict(cfg.refine), sort_keys=True).encode()),
    }
    if refine:
        from transcription_study.refinement import refinement_metadata

        settings["refinement"] = refinement_metadata(cfg.refine)
    model_path = Path(cfg.asr.model)
    if not model_path.is_dir():
        model_path = Path(download_model(cfg.asr.model, local_files_only=True))
    model_files = {}
    for path in sorted(model_path.iterdir()):
        if path.is_file():
            # HF blob names pin the immutable model weights without reading a
            # multi-gigabyte binary before every resumed screen.
            model_files[path.name] = {
                "bytes": path.stat().st_size,
                "blob": path.resolve().name if path.is_symlink() else None,
                "sha256": file_digest(path)
                if path.suffix != ".bin" or not path.is_symlink()
                else None,
            }
    return {
        "version": 1,
        "manifest_sha256": digest(manifest_path.read_bytes()),
        "config": settings,
        "profiles": [asdict(profile) for profile in profiles],
        "versions": versions,
        "sources": {str(path.relative_to(root)): digest(path.read_bytes()) for path in sources},
        "python": sys.version.split()[0],
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(),
        },
        "model": {"snapshot": model_path.name, "files": model_files},
        "normalization": (
            "NFKC, casefold, curly-apostrophe canonicalization; "
            "lexical words, contractions and numeric values"
        ),
    }


def fingerprint(metadata: dict, profile: str) -> str:
    """Profile selection/order does not invalidate an otherwise identical comparison."""
    data = {**metadata, "profiles": [p for p in metadata["profiles"] if p["id"] == profile]}
    return digest(json.dumps(data, sort_keys=True, allow_nan=False).encode())


def completed_rows(path: Path) -> set[tuple[str, str, str]]:
    """Read complete checkpoints, tolerating only an interrupted final JSON line."""
    if not path.exists():
        return set()
    lines = path.read_text().splitlines()
    found = set()
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                continue
            raise
        found.add((row["fingerprint"], row["clip_id"], row["split"]))
    return found


def memory_usage() -> dict:
    """Process lifetime high-water mark, explicitly distinguished from per-clip peak."""
    import psutil

    info = psutil.Process().memory_info()
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
    except ImportError:
        peak_bytes = getattr(info, "peak_wset", None)
    return {
        "rss_bytes": info.rss,
        "rss_peak_bytes": peak_bytes,
        "rss_peak_scope": "worker_process_lifetime",
    }


def measure_clip(clip: dict, profile, cfg: Config, decoder, *, refine: bool = False) -> dict:
    """Evaluate a file and discard all hypotheses after reducing them to numbers."""
    import numpy as np
    import soundfile as sf
    from transcription_study.audio import transform

    started = time.monotonic()
    reference = Path(clip["reference_path"]).read_text(encoding="utf-8")
    audio_path = Path(clip["audio_path"])
    if digest(audio_path.read_bytes()) != clip["sha256"]:
        raise ValueError("audio_checksum_mismatch")
    if digest(Path(clip["reference_path"]).read_bytes()) != clip["reference_sha256"]:
        raise ValueError("reference_checksum_mismatch")
    samples, source_rate = sf.read(audio_path, dtype="float32", always_2d=False)
    # Recorder retains channel 0 before resampling. Transform first selects the
    # channel; gain, padding and normalization then operate at the source rate.
    selected = transform(samples, source_rate, channel=profile.audio.get("channel", "first"))
    samples = transform(samples, source_rate, **profile.audio)
    input_peak = float(np.max(np.abs(selected))) if selected.size else 0.0
    output_peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    input_rms = float(np.sqrt(np.mean(selected.astype(np.float64) ** 2))) if selected.size else 0.0
    output_rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0
    gain_only = not any(
        profile.audio.get(key, 0)
        for key in ("leading_ms", "trailing_ms", "trim_leading_ms", "trim_trailing_ms")
    )
    effective_gain_db = (
        float(20 * np.log10(output_rms / input_rms))
        if gain_only and input_rms > 0 and output_rms > 0
        else None
    )
    audio_metrics = {
        "input_peak": input_peak,
        "output_peak": output_peak,
        "input_rms": input_rms,
        "output_rms": output_rms,
        "requested_gain_db": profile.audio.get("gain_db", 0),
        "normalize_rms_dbfs": profile.audio.get("normalize_rms_dbfs"),
        "effective_gain_db": effective_gain_db,
        "clipped_input_samples": int(np.count_nonzero(np.abs(selected) >= 1)),
        "clipped_output_samples": int(np.count_nonzero(np.abs(samples) >= 1)),
    }
    samples = _resample_poly(samples, source_rate, SAMPLE_RATE)
    threshold = cfg.audio.min_speech_rms if profile.gate_rms is None else profile.gate_rms
    gate = speech_gate_stats(samples, SAMPLE_RATE, threshold)
    result = {
        "texts": {"raw": None, "assembled": None, "formatted": ""},
        "status": "gate_rejected",
        "error_type": None,
        "vad_seconds": None,
        "decode_seconds": 0,
        "segments_raw": 0,
        "segments_kept": 0,
    }
    if gate.passed:
        decode_start = time.monotonic()
        try:
            result = decoder.transcribe(samples, profile)
        except Exception as exc:
            result.update(
                status="decode_error",
                error_type=type(exc).__name__,
                decode_seconds=time.monotonic() - decode_start,
            )
    texts = result.pop("texts")
    result["stages"] = {
        stage: score(reference, text) if text is not None else None for stage, text in texts.items()
    }
    if refine:
        from transcription_study.refinement import evaluate_refinement

        result["refinement"] = evaluate_refinement(
            texts["formatted"],
            reference,
            cfg.refine,
            idle_unload_seconds=cfg.asr.idle_unload_seconds,
        )
    result.update(
        version=1,
        clip_id=clip["id"],
        split=clip["split"],
        corpus=clip["corpus"],
        group=clip["group"],
        profile=profile.id,
        gate=asdict(gate),
        audio_seconds=len(samples) / SAMPLE_RATE,
        source_sample_rate=source_rate,
        wall_seconds=time.monotonic() - started,
        backend=decoder.backend,
        audio_metrics=audio_metrics,
    )
    result.update(memory_usage())
    return result


def worker(args) -> int:
    # Offline model resolution is mandatory, including dependencies using HF.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    logging.disable(logging.CRITICAL)
    from transcription_study.decode import Decoder

    config_path = args.config or resolve_config_path(create_parent=False)
    cfg = Config.load(config_path) if config_path.is_file() else Config.defaults()
    cfg = override_config(
        cfg, model=args.model, compute_type=args.compute_type, cpu_threads=args.cpu_threads
    )
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("version") != 1:
        raise ValueError("unsupported_manifest_version")
    profiles = [PROFILES[name] for name in args.profiles.split(",")]
    clips = select_clips(manifest, args.split, args.limit)
    if not clips:
        raise ValueError("empty_selection")
    metadata = run_metadata(args.manifest, cfg, profiles, args.refine)
    decoder = Decoder(cfg.asr)
    metadata["backend"] = decoder.backend
    fingerprints = {profile.id: fingerprint(metadata, profile.id) for profile in profiles}
    done = completed_rows(args.output) if args.resume else set()
    jobs = [
        (clip, profile)
        for clip in clips
        for profile in profiles
        if (fingerprints[profile.id], clip["id"], clip["split"]) not in done
    ]
    random.Random(manifest.get("seed", 20260912)).shuffle(jobs)
    if not jobs:
        decoder.close()
        print(json.dumps({"status": "already_complete", "completed": 0}))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = Path(str(args.output) + ".meta.json")
    previous = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    for profile in profiles:
        previous[fingerprints[profile.id]] = {
            **metadata,
            "active_profile": profile.id,
            "started_utc": datetime.now(UTC).isoformat(),
        }
    sidecar.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n")
    for key in fingerprints.values():
        previous[key].update(backend=decoder.backend, cold_load_seconds=decoder.load_seconds)
    sidecar.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n")
    # Repair only an incomplete final checkpoint before append; complete rows stay.
    if args.output.exists():
        data = args.output.read_bytes()
        if data and not data.endswith(b"\n"):
            last = data.rfind(b"\n")
            try:
                json.loads(data[last + 1 :])
            except json.JSONDecodeError:
                args.output.write_bytes(data[: last + 1])
            else:
                with args.output.open("ab") as stream:
                    stream.write(b"\n")
    finished = 0
    decode_attempted = False
    with args.output.open("a", encoding="utf-8") as stream:
        for clip, profile in jobs:
            row = measure_clip(clip, profile, cfg, decoder, refine=args.refine)
            row["first_decode_in_worker"] = row["gate"]["passed"] and not decode_attempted
            decode_attempted = decode_attempted or row["gate"]["passed"]
            row["fingerprint"] = fingerprints[profile.id]
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            finished += 1
            print(
                json.dumps(
                    {
                        "completed": finished,
                        "total": len(jobs),
                        "profile": profile.id,
                        "clip_id": clip["id"],
                        "status": row["status"],
                    }
                ),
                flush=True,
            )
    decoder.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model", help="Override cached model for this benchmark only")
    parser.add_argument("--compute-type", help="Override CTranslate2 compute type for this run")
    parser.add_argument("--cpu-threads", type=int, help="Override CPU threads; 0 selects automatic")
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--profiles", default="baseline", help=", ".join(PROFILES))
    parser.add_argument("--max-seconds", type=float, default=3600)
    parser.add_argument(
        "--deadline", help="Absolute ISO-8601 UTC deadline, e.g. 2026-09-12T03:08:35Z"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--refine", action="store_true", help="Evaluate configured loopback refinement"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.max_seconds <= 0:
        parser.error("limit and max-seconds must be positive")
    if args.cpu_threads is not None and args.cpu_threads < 0:
        parser.error("cpu-threads must be nonnegative")
    if any(name not in PROFILES for name in args.profiles.split(",")):
        parser.error("unknown profile")
    if args.output.exists() and not args.resume and not args.worker:
        parser.error("output exists; use --resume or a new output path")
    if args.worker:
        try:
            return worker(args)
        except Exception as exc:
            print(
                json.dumps({"status": "error", "error_type": type(exc).__name__}), file=sys.stderr
            )
            return 1
    budget = args.max_seconds
    if args.deadline:
        deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        budget = min(budget, (deadline - datetime.now(UTC)).total_seconds())
    if budget <= 0:
        print(json.dumps({"status": "deadline_reached"}))
        return 2
    child_args = list(sys.argv[1:] if argv is None else argv)
    try:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *child_args, "--worker"],
            timeout=budget,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "deadline_reached", "checkpoint": str(args.output)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
