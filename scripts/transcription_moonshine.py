# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline Moonshine diagnostic using the shared public-corpus lexical scorer.

Requires moonshine-voice==0.1.5 in a separate study environment and pre-downloaded
model files. This script never downloads, captures, plays, or logs speech.
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
import wave
from datetime import UTC, datetime
from pathlib import Path

from transcription_study.profiles import select_clips
from transcription_study.scoring import score


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def worker(args) -> int:
    """Load only local model files and retain only numeric recognition results."""
    logging.disable(logging.CRITICAL)
    import numpy as np
    from moonshine_voice import ModelArch, Transcriber

    if importlib.metadata.version("moonshine-voice") != "0.1.5":
        raise ValueError("unverified_moonshine_version")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("unsupported_manifest_version")
    clips = select_clips(manifest, "dev", args.limit)
    if not clips:
        raise ValueError("empty_development_selection")
    model_files = {p.name: digest(p) for p in sorted(args.model_path.iterdir()) if p.is_file()}
    if not model_files:
        raise ValueError("missing_local_model_files")
    options = {
        "ort_providers": "CPU",
        "log_api_calls": "false",
        "log_output_text": "false",
        "return_audio_data": "false",
    }
    metadata = {
        "version": 1,
        "manifest_sha256": digest(args.manifest),
        "adapter_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(Path(__file__).parent / "transcription_study/scoring.py"),
        "engine": "moonshine-voice",
        "engine_version": "0.1.5",
        "model_arch": args.model_arch,
        "model_files": model_files,
        "options": options,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "started_utc": datetime.now(UTC).isoformat(),
        "comparison_scope": "Native engine output, including its own VAD; no application filtering",
    }
    fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    started = time.monotonic()
    with Transcriber(args.model_path, ModelArch(args.model_arch), options=options) as transcriber:
        metadata["cold_load_seconds"] = time.monotonic() - started
        Path(str(args.output) + ".meta.json").write_text(
            json.dumps({fingerprint: metadata}, indent=2) + "\n", encoding="utf-8"
        )
        random.Random(manifest.get("seed", 20260912)).shuffle(clips)
        with args.output.open("x", encoding="utf-8") as output:
            for index, clip in enumerate(clips):
                started = time.monotonic()
                audio_path = Path(clip["audio_path"])
                reference_path = Path(clip["reference_path"])
                if digest(audio_path) != clip["sha256"]:
                    raise ValueError("audio_checksum_mismatch")
                if digest(reference_path) != clip["reference_sha256"]:
                    raise ValueError("reference_checksum_mismatch")
                with wave.open(str(audio_path)) as source:
                    if source.getnchannels() != 1 or source.getsampwidth() != 2:
                        raise ValueError("expected_mono_pcm16_wav")
                    rate = source.getframerate()
                    audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
                samples = audio.astype(np.float32) / 32768
                reference = reference_path.read_text(encoding="utf-8")
                decode_start = time.monotonic()
                status, error_type, hypothesis = "ok", None, ""
                try:
                    transcript = transcriber.transcribe_without_streaming(samples.tolist(), rate)
                    hypothesis = " ".join(line.text for line in transcript.lines)
                except Exception as error:
                    status, error_type = "decode_error", type(error).__name__
                decode_seconds = time.monotonic() - decode_start
                row = {
                    "version": 1,
                    "fingerprint": fingerprint,
                    "clip_id": clip["id"],
                    "split": "dev",
                    "corpus": clip["corpus"],
                    "group": clip["group"],
                    "profile": "moonshine_native",
                    "status": status,
                    "error_type": error_type,
                    "stages": {"raw": score(reference, hypothesis)},
                    "decode_seconds": decode_seconds,
                    "wall_seconds": time.monotonic() - started,
                    "audio_seconds": len(samples) / rate,
                    "first_decode_in_worker": index == 0,
                    "backend": {"device": "cpu", "compute_type": "publisher_quantized_ort"},
                }
                output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                output.flush()
                print(
                    json.dumps({"completed": index + 1, "total": len(clips), "status": status}),
                    flush=True,
                )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-arch", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-seconds", type=float, default=300)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.limit <= 0 or args.max_seconds <= 0:
        parser.error("limit and max-seconds must be positive")
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    if not args.model_path.is_dir():
        parser.error("model-path must contain pre-downloaded model files")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        try:
            return worker(args)
        except Exception as error:
            Path(str(args.output) + ".error.json").write_text(
                json.dumps({"status": "error", "error_type": type(error).__name__}) + "\n",
                encoding="utf-8",
            )
            return 1
    # Native library diagnostics cannot expose speech through the parent's pipes.
    # Numeric checkpoints remain available even when the child times out.
    with open(os.devnull, "w") as muted:
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"],
                stdout=muted,
                stderr=muted,
                timeout=args.max_seconds,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"status": "time_budget_exhausted"}))
            return 2
    error_record = Path(str(args.output) + ".error.json")
    if result.returncode and error_record.exists():
        print(error_record.read_text(encoding="utf-8").strip())
    else:
        print(json.dumps({"status": "complete" if result.returncode == 0 else "worker_failed"}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
