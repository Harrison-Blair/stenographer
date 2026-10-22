# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared driver for the Bark evaluation: the same clips, phrases and metrics for every runtime.

Each runner supplies load() -> decoder and decoder(samples) -> (text, words), where words is a
list of (start_s, end_s, word) relative to the samples (None when the runtime gives none).
Output JSON goes to a path under .scratch/ (it holds transcripts; never commit it).
Needs only numpy, soundfile and the standard library, so it runs in both venvs.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

WORKTREE = Path(__file__).resolve().parents[7]
CORPUS = Path("/home/penguin/source/stenographer/.cache/transcription-study-20260912")
EXCERPTS = WORKTREE / ".scratch/audio"
PHRASES = WORKTREE / ".scratch/phrases"
RATE = 16000


def corpus_clips() -> list[dict]:
    clips = json.loads((CORPUS / "manifest.json").read_text())["clips"]
    return [
        {
            "id": c["id"],
            "corpus": c["corpus"],
            "split": c["split"],
            "audio": c["audio_path"],
            "reference": Path(c["reference_path"]).read_text().strip(),
        }
        for c in clips
    ]


def excerpt_phrases() -> list[dict]:
    out = []
    for path in sorted(PHRASES.glob("excerpt*.json")):
        audio, rate = sf.read(EXCERPTS / f"{path.stem}.wav", dtype="float32")
        assert rate == RATE
        for i, (start, end) in enumerate(json.loads(path.read_text())):
            out.append(
                {
                    "excerpt": path.stem,
                    "index": i,
                    "start": start,
                    "end": end,
                    "samples": audio[round(start * RATE) : round(end * RATE)],
                }
            )
    return out


def _rss_mb(field: str) -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1]) / 1024
    return float("nan")


class GpuSampler:
    """Peak GPU memory of this process from nvidia-smi, sampled every 0.2 s."""

    def __init__(self) -> None:
        self.peak_mb = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        pid = str(os.getpid())
        while not self._stop.is_set():
            try:
                rows = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,used_memory",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
                for row in rows.splitlines():
                    p, mem = (x.strip() for x in row.split(","))
                    if p == pid:
                        self.peak_mb = max(self.peak_mb, int(mem))
            except Exception:
                pass
            self._stop.wait(0.2)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def micro(label: str, load, out_path: str, meta: dict, sync) -> None:
    """Median of 10 decodes (after one warm-up) of the public clips nearest 3 s and 8 s."""
    clips = corpus_clips()
    t0 = time.perf_counter()
    decode = load()
    sync()
    load_s = time.perf_counter() - t0
    result = {"label": label, **meta, "load_s": load_s, "loadavg_start": os.getloadavg()[0]}
    for target in (3.0, 8.0):
        c = min(clips, key=lambda c: abs(sf.info(c["audio"]).duration - target))
        audio, _ = sf.read(c["audio"], dtype="float32")
        decode(audio)
        sync()
        lats = []
        for _ in range(10):
            t = time.perf_counter()
            decode(audio)
            sync()
            lats.append(time.perf_counter() - t)
        result[f"clip_{target:.0f}s"] = {
            "id": c["id"],
            "duration": len(audio) / RATE,
            "median_ms": 1000 * float(np.median(lats)),
            "min_ms": 1000 * min(lats),
        }
    result["loadavg_end"] = os.getloadavg()[0]
    result["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    Path(out_path).write_text(json.dumps(result))
    print(json.dumps(result))


def run(label: str, load, out_path: str, meta: dict, sync=lambda: None) -> None:
    """Load once, warm up on one clip, then decode every corpus clip and every excerpt phrase."""
    if os.environ.get("BENCH_MICRO"):
        return micro(label, load, out_path, meta, sync)
    clips = corpus_clips()
    phrases = excerpt_phrases()
    with GpuSampler() as gpu:
        t0 = time.perf_counter()
        decode = load()
        sync()
        load_s = time.perf_counter() - t0
        rss_after_load = _rss_mb("VmRSS")
        warm, _ = sf.read(clips[0]["audio"], dtype="float32")
        t0 = time.perf_counter()
        decode(warm)
        sync()
        first_decode_s = time.perf_counter() - t0

        def timed(samples):
            t = time.perf_counter()
            text, words = decode(samples)
            sync()
            return text, words, time.perf_counter() - t

        corpus = []
        for c in clips:
            audio, rate = sf.read(c["audio"], dtype="float32")
            assert rate == RATE
            text, words, lat = timed(audio)
            corpus.append(
                {
                    **{k: c[k] for k in ("id", "corpus", "split", "reference")},
                    "duration": len(audio) / RATE,
                    "text": text,
                    "words": words,
                    "latency": lat,
                }
            )
        excerpts = []
        for p in phrases:
            text, words, lat = timed(p["samples"])
            excerpts.append(
                {
                    "excerpt": p["excerpt"],
                    "index": p["index"],
                    "start": p["start"],
                    "end": p["end"],
                    "duration": len(p["samples"]) / RATE,
                    "text": text,
                    "words": words,
                    "latency": lat,
                }
            )
    result = {
        "label": label,
        **meta,
        "python": sys.version.split()[0],
        "load_s": load_s,
        "first_decode_s": first_decode_s,
        "rss_after_load_mb": rss_after_load,
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "peak_gpu_mb": gpu.peak_mb,
        "corpus": corpus,
        "excerpts": excerpts,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result))
    lat_c = sum(r["latency"] for r in corpus) / sum(r["duration"] for r in corpus)
    lat_e = sum(r["latency"] for r in excerpts) / sum(r["duration"] for r in excerpts)
    print(
        f"{label}: load {load_s:.1f}s first {first_decode_s:.2f}s RTF corpus {lat_c:.4f} "
        f"excerpts {lat_e:.4f} peak RSS {result['peak_rss_mb']:.0f} MB GPU {gpu.peak_mb} MB"
    )


def words_from_pieces(pieces) -> list:
    """Group (text, start, end) token pieces into words: a new word starts at a leading space."""
    words: list[list] = []
    for text, start, end in pieces:
        if not text:
            continue
        if not words or text.startswith((" ", "▁")):
            stripped = text.lstrip(" ▁")
            if stripped:
                words.append([start, end, stripped])
            continue
        if not any(ch.isalnum() for ch in text):
            words[-1][2] += text  # punctuation keeps the previous word's span
            continue
        words[-1][1] = max(words[-1][1], end)
        words[-1][2] += text
    return [(round(s, 3), round(e, 3), w) for s, e, w in words]
