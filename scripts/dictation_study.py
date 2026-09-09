# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in, file-only ASR study. Never records, plays, copies, pastes, or downloads models.

Run with .venv/bin/python scripts/dictation_study.py --help. Public acquisition
is a separate explicit subcommand; inference reads only a sealed local corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import random
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from stenographer.config import Config
from stenographer.constants import SAMPLE_RATE
from stenographer.evaluation import alignment, completed_chunks, distribution
from stenographer.transcribe.model import (
    Model,
    SegmentInfo,
    TranscriptionResult,
    WordInfo,
    _assemble,
    _token_budget,
)
from stenographer.transcribe.pipeline import transcript_text
from stenographer.transcribe.reconcile import Window, reconcile

SEED = 20260906
# Earlier audio investigation used offsets <= 2100. These are new recordings;
# speakers are checked across splits before the acquired manifest is written.
OFFSETS = {"development": (2200, 2300), "holdout": (2400, 2500)}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_public(destination: Path) -> None:
    """Explicit public/licensed corpus acquisition, independent of application ASR."""
    import soundfile as sf

    destination.mkdir(parents=True, exist_ok=False)
    cases = []
    for split, offsets in OFFSETS.items():
        for config in ("clean", "other"):
            for offset in offsets:
                query = urllib.parse.urlencode(
                    dict(
                        dataset="openslr/librispeech_asr",
                        config=config,
                        split="test",
                        offset=offset,
                        length=1,
                    )
                )
                with urllib.request.urlopen(
                    "https://datasets-server.huggingface.co/rows?" + query, timeout=45
                ) as response:
                    row = json.load(response)["rows"][0]["row"]
                with urllib.request.urlopen(row["audio"][0]["src"], timeout=45) as response:
                    audio, rate = sf.read(io.BytesIO(response.read()), dtype="float32")
                if rate != SAMPLE_RATE or audio.ndim != 1:
                    raise ValueError("unexpected public audio format")
                case_id = f"{config}-{offset}"
                path = destination / f"{case_id}.wav"
                sf.write(path, audio, rate, subtype="FLOAT")
                cases.append(
                    dict(
                        id=case_id,
                        source_id=row["id"],
                        speaker=str(row["speaker_id"]),
                        split=split,
                        audio=path.name,
                        sha256=digest(path.read_bytes()),
                        reference=row["text"],
                        source="https://www.openslr.org/12/",
                        license="CC-BY-4.0",
                        profile="original",
                    )
                )
    speakers = [{c["speaker"] for c in cases if c["split"] == split} for split in OFFSETS]
    if speakers[0] & speakers[1]:
        raise ValueError("cross-split speaker overlap; choose new offsets before using corpus")
    (destination / "manifest.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


def waveform(audio: np.ndarray, profile: str) -> np.ndarray:
    if profile == "original":
        return audio
    if profile == "quiet-opening":
        changed = audio.copy()
        changed[:SAMPLE_RATE] *= 0.1
        return changed
    if profile == "silence-tail":
        return np.concatenate((audio, np.zeros(SAMPLE_RATE * 15, dtype=np.float32)))
    if profile == "noise-tail":
        noise = np.random.default_rng(SEED).normal(0, 0.002, SAMPLE_RATE * 15).astype(np.float32)
        return np.concatenate((audio, noise))
    raise ValueError("unknown profile")


def compose(manifest: Path, destination: Path, seconds: int) -> None:
    """Repeat complete DEVELOPMENT clips for scheduling stress, not natural-speech accuracy."""
    import soundfile as sf

    cases = [
        c for c in json.loads(manifest.read_text(encoding="utf-8")) if c["split"] == "development"
    ]
    if not cases:
        raise ValueError("no development audio")
    blocks, references, source_ids = [], [], []
    total = 0
    while total < seconds * SAMPLE_RATE:
        for case in cases:
            path = (manifest.parent / case["audio"]).resolve()
            if (
                not path.is_relative_to(manifest.parent.resolve())
                or case["license"] != "CC-BY-4.0"
                or digest(path.read_bytes()) != case["sha256"]
            ):
                raise ValueError("invalid public fixture")
            audio, rate = sf.read(path, dtype="float32")
            if rate != SAMPLE_RATE or audio.ndim != 1 or not len(audio):
                raise ValueError("invalid audio geometry")
            blocks.append(audio)
            blocks.append(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
            references.append(case["reference"])
            source_ids.append(case["source_id"])
            total += len(audio) + SAMPLE_RATE // 2
            if total >= seconds * SAMPLE_RATE:
                break
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "composite.wav"
    sf.write(path, np.concatenate(blocks), SAMPLE_RATE, subtype="FLOAT")
    document = [
        dict(
            id=f"composite-{seconds}s",
            split="development",
            speaker="composite-development",
            audio=path.name,
            sha256=digest(path.read_bytes()),
            reference=" ".join(references),
            source_ids=source_ids,
            source_manifest_sha256=digest(manifest.read_bytes()),
            license="CC-BY-4.0",
            profile="repeated-development-stress-only",
        )
    ]
    (destination / "manifest.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def batched(model: Model, samples: np.ndarray):
    """Candidate, not equivalent: faster-whisper 1.2.1 batching ignores some gates.

    Reapply the repository's no-speech and output-validation stages. This remains
    an explicit study candidate; never silently select it for production.
    """
    from faster_whisper import BatchedInferencePipeline

    from stenographer.transcribe.model import _VAD_PARAMETERS

    cfg = model._cfg
    iterator, info = BatchedInferencePipeline(model._impl).transcribe(
        samples,
        language="en",
        beam_size=cfg.beam_size,
        temperature=0.0,
        no_repeat_ngram_size=3,
        vad_filter=True,
        vad_parameters=dict(_VAD_PARAMETERS),
        no_speech_threshold=cfg.silence_threshold,
        hallucination_silence_threshold=2.0,
        max_new_tokens=_token_budget(128, len(samples) / SAMPLE_RATE),
        condition_on_previous_text=False,
        word_timestamps=True,
        hotwords=cfg.hotwords,
        initial_prompt=cfg.initial_prompt,
        batch_size=4,
    )
    segments = [
        SegmentInfo(
            float(s.start),
            float(s.end),
            s.text,
            float(s.no_speech_prob),
            [
                WordInfo(float(w.start), float(w.end), w.word, float(w.probability))
                for w in s.words or ()
            ],
        )
        for s in iterator
    ]
    return _assemble(
        segments,
        silence_threshold=cfg.silence_threshold,
        audio_seconds=len(samples) / SAMPLE_RATE,
        vad_seconds=info.duration_after_vad,
    )


def replay(model: Model, samples: np.ndarray) -> tuple[TranscriptionResult, dict]:
    """Wall-clock file replay with one active inference and no pending queue.

    No PortAudio stream is involved. The original waveform stays available for
    fallback. This measures scheduling/finalization, not microphone continuity,
    OS scheduling priority, or actual delivery latency. No production deadlines
    or child-crash isolation are implied by this in-process study adapter.
    """
    duration = len(samples) / SAMPLE_RATE
    stop_at = time.perf_counter() + duration
    started_at = stop_at - duration
    windows: list[Window] = []
    future = None
    active = None
    index = 0
    failed = False
    with ThreadPoolExecutor(max_workers=1) as executor:
        while time.perf_counter() < stop_at:
            available = min(len(samples), int((time.perf_counter() - started_at) * SAMPLE_RATE))
            ready = completed_chunks(available, size=30 * SAMPLE_RATE, overlap=3 * SAMPLE_RATE)
            if future is not None and future.done():
                try:
                    windows.append(
                        Window(
                            active.start / SAMPLE_RATE, active.end / SAMPLE_RATE, future.result()
                        )
                    )
                except Exception:
                    failed = True
                future = None
            if len(ready) > index + 1:
                failed = True  # no accumulating queue; finish via original audio
            if not failed and future is None and index < len(ready):
                active = ready[index]
                future = executor.submit(model.transcribe, samples[active.start : active.end])
                index += 1
            time.sleep(min(0.05, max(0, stop_at - time.perf_counter())))
        if future is not None:
            try:
                windows.append(
                    Window(active.start / SAMPLE_RATE, active.end / SAMPLE_RATE, future.result())
                )
            except Exception:
                failed = True
        if not failed:
            tail_start = (
                max(0, int(windows[-1].end * SAMPLE_RATE) - 3 * SAMPLE_RATE) if windows else 0
            )
            if not windows or windows[-1].end < duration:
                try:
                    tail = model.transcribe(samples[tail_start:])
                    windows.append(Window(tail_start / SAMPLE_RATE, duration, tail))
                except Exception:
                    failed = True
        merged = reconcile(windows, duration)
        fallback = failed or merged.failure is not None
        result = (
            model.transcribe(samples)
            if fallback
            else TranscriptionResult(text=merged.value, duration_seconds=duration)
        )
    return result, dict(
        stop_to_ready_ms=(time.perf_counter() - stop_at) * 1000,
        fallback=int(fallback),
        completed_windows=len(windows),
        capture_overflow=None,
    )


def load_fixtures(
    manifest: Path, split: str, *, unlock_holdout: bool = False
) -> tuple[bytes, list[dict[str, Any]], dict[str, np.ndarray]]:
    """Validate the sealed corpus before opening any evidence output or model."""
    import soundfile as sf

    if split == "holdout" and not unlock_holdout:
        raise ValueError("holdout requires explicit --unlock-holdout after candidate freeze")
    raw_manifest = manifest.read_bytes()
    cases = json.loads(raw_manifest)
    selected = [c for c in cases if c["split"] == split]
    if not selected or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("empty split or duplicate case IDs")
    speakers = [{c["speaker"] for c in cases if c["split"] == split} for split in OFFSETS]
    if speakers[0] & speakers[1]:
        raise ValueError("cross-split speaker overlap")
    fixtures = {}
    for case in selected:
        path = (manifest.parent / case["audio"]).resolve()
        if not path.is_relative_to(manifest.parent.resolve()):
            raise ValueError("audio path escapes corpus")
        if not case["license"] or digest(path.read_bytes()) != case["sha256"]:
            raise ValueError("unlicensed or changed fixture")
        audio, rate = sf.read(path, dtype="float32")
        if rate != SAMPLE_RATE or audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError("expected finite mono 16 kHz audio")
        fixtures[case["id"]] = audio
    return raw_manifest, selected, fixtures


def run_trial(
    model: Model,
    case: dict[str, Any],
    audio: np.ndarray,
    *,
    profile: str,
    variant: str,
    repeat: int,
) -> dict[str, Any]:
    """Run one candidate and its separate VAD diagnostic; retain counts only."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    from stenographer.transcribe.model import _VAD_PARAMETERS

    audio = waveform(audio, profile)
    synthetic_frames = SAMPLE_RATE // 2 if variant == "prefix-500ms" else 0
    samples = np.concatenate((np.zeros(synthetic_frames, dtype=np.float32), audio))
    row = dict(
        kind="trial",
        case=case["id"],
        profile=profile,
        variant=variant,
        repeat=repeat,
        audio_s=len(audio) / SAMPLE_RATE,
        synthetic_frames=synthetic_frames,
        failure=None,
    )
    started = time.perf_counter()
    try:
        if variant == "replay":
            result, replay_metrics = replay(model, samples)
            row.update(replay_metrics)
        else:
            result = batched(model, samples) if variant == "batched" else model.transcribe(samples)
        row["decode_ms"] = (time.perf_counter() - started) * 1000
        if variant == "replay":
            row["replay_wall_ms"] = row.pop("decode_ms")
        formatted = transcript_text(result)
        row.update(alignment(case["reference"], formatted))
        row["vad_s"] = None if variant == "replay" else result.vad_seconds
        # Separate diagnostic run, outside decode timing. These are NOT
        # claimed as the batched decoder's effective boundary intervals.
        vad_started = time.perf_counter()
        intervals = get_speech_timestamps(samples, VadOptions(**_VAD_PARAMETERS))
        row["vad_probe_ms"] = (time.perf_counter() - vad_started) * 1000
        row["vad_probe_first_frame"] = intervals[0]["start"] if intervals else None
        row["vad_probe_last_frame"] = intervals[-1]["end"] if intervals else None
        row["vad_probe_intervals"] = len(intervals)
    except Exception as exc:
        row["decode_ms"] = (time.perf_counter() - started) * 1000
        row["failure"] = type(exc).__name__
    return row


def summarize_trials(records: list[dict[str, Any]], variants: list[str]) -> list[dict[str, Any]]:
    """Aggregate successful trials in requested order; absent timings stay absent. PURE."""
    summaries = []
    for variant in variants:
        rows = [r for r in records if r["variant"] == variant]
        successful = [r for r in rows if r["failure"] is None]
        summaries.append(
            dict(
                kind="summary",
                variant=variant,
                trials=len(rows),
                failures=len(rows) - len(successful),
                decode_ms=distribution([r["decode_ms"] for r in successful if "decode_ms" in r]),
                stop_to_ready_ms=distribution(
                    [r["stop_to_ready_ms"] for r in successful if "stop_to_ready_ms" in r]
                ),
                fallbacks=sum(r.get("fallback", 0) for r in successful),
                errors=sum(r["errors"] for r in successful),
                reference_words=sum(r["reference_words"] for r in successful),
                empty=sum(r["empty"] for r in successful),
                tail_insertions=sum(r["tail_insertions"] for r in successful),
                opening_exact=sum(r["opening_exact"] for r in successful),
            )
        )
    return summaries


def run(args: argparse.Namespace) -> None:
    raw_manifest, selected, fixtures = load_fixtures(
        args.manifest, args.split, unlock_holdout=args.unlock_holdout
    )
    jobs = [
        (c, p, v, r)
        for c in selected
        for p in args.profiles
        for v in args.variants
        for r in range(args.repeats)
    ]
    random.Random(SEED).shuffle(jobs)
    cfg = replace(Config.defaults().asr, cpu_threads=args.cpu_threads)
    records = []
    # Exclusive creation protects evidence from accidental reruns/overwrites.
    with args.output.open("x", encoding="utf-8") as output:
        metadata = dict(
            kind="metadata",
            schema=1,
            revision=args.revision,
            seed=SEED,
            manifest_sha256=digest(raw_manifest),
            runner_sha256=digest(Path(__file__).read_bytes()),
            split=args.split,
            config=asdict(cfg),
            versions={name: version(name) for name in ("faster-whisper", "ctranslate2", "numpy")},
            pending_measurements=["physical_capture", "cleanup", "paste", "peak_memory"],
        )
        output.write(json.dumps(metadata) + "\n")
        output.flush()
        started = time.perf_counter()
        model = Model(cfg)
        output.write(
            json.dumps(
                dict(
                    kind="load",
                    load_ms=(time.perf_counter() - started) * 1000,
                    cpu_threads=model.cpu_threads,
                    device=model._impl.model.device,
                    compute_type=model._impl.model.compute_type,
                )
            )
            + "\n"
        )
        try:
            for case, profile, variant, repeat in jobs:
                row = run_trial(
                    model,
                    case,
                    fixtures[case["id"]],
                    profile=profile,
                    variant=variant,
                    repeat=repeat,
                )
                records.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
        finally:
            model.close()
        for summary in summarize_trials(records, args.variants):
            output.write(json.dumps(summary) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch-public", help="explicitly download eight CC-BY-4.0 speech clips")
    fetch.add_argument("destination", type=Path)
    composite = sub.add_parser(
        "compose", help="repeat complete development clips for timing stress"
    )
    composite.add_argument("manifest", type=Path)
    composite.add_argument("destination", type=Path)
    composite.add_argument("--seconds", type=int, choices=(60, 180, 300, 600), required=True)
    study = sub.add_parser("run", help="offline file decoding; no microphone or delivery")
    study.add_argument("manifest", type=Path)
    study.add_argument("output", type=Path)
    study.add_argument(
        "--revision", required=True, help="source revision and dirty-tree description"
    )
    study.add_argument("--split", choices=tuple(OFFSETS), default="development")
    study.add_argument("--unlock-holdout", action="store_true")
    study.add_argument(
        "--variants",
        nargs="+",
        choices=("baseline", "prefix-500ms", "batched", "replay"),
        default=["baseline", "prefix-500ms", "batched"],
    )
    study.add_argument(
        "--profiles",
        nargs="+",
        choices=("original", "quiet-opening", "silence-tail", "noise-tail"),
        default=["original", "quiet-opening", "silence-tail", "noise-tail"],
    )
    study.add_argument("--repeats", type=int, default=3)
    study.add_argument("--cpu-threads", type=int, default=0)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        if args.command == "fetch-public":
            fetch_public(args.destination)
        elif args.command == "compose":
            compose(args.manifest, args.destination, args.seconds)
        else:
            if args.repeats < 1 or args.cpu_threads < 0:
                parser.error("repeats must be positive and cpu-threads nonnegative")
            run(args)
    except Exception as exc:
        # Inference exceptions can contain decoded text. Never print their messages.
        print(json.dumps(dict(kind="failure", failure=type(exc).__name__)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
