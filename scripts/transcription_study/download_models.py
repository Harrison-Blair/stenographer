# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicitly download the three pinned Whisper candidates for the study.

Only model components are fetched. Every completed candidate receives a local
provenance manifest with checksums; no model is loaded and no audio is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

CANDIDATES = {
    "turbo": (
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        1_621_665_983,
    ),
    "distil": (
        "Systran/faster-distil-whisper-large-v3",
        "c3058b475261292e64a0412df1d2681c06260fab",
        1_516_479_628,
    ),
    "large-v3": (
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        3_090_835_702,
    ),
}
COMPONENTS = {
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "vocabulary.json",
    "preprocessor_config.json",
}


def download_candidate(name: str, root: Path) -> None:
    """Preflight one fixed component list and record the completed file hashes."""
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_XET_CACHE"] = str(root / "xet-cache")
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    from huggingface_hub import HfApi, snapshot_download

    repo, revision, expected_bytes = CANDIDATES[name]
    info = HfApi(token=False).model_info(repo, revision=revision, files_metadata=True)
    files = {
        entry.rfilename: entry.size for entry in info.siblings if entry.rfilename in COMPONENTS
    }
    if info.sha != revision or sum(files.values()) != expected_bytes:
        raise ValueError("pinned component metadata mismatch")
    destination = root / name
    snapshot_download(
        repo,
        revision=revision,
        local_dir=destination,
        token=False,
        allow_patterns=sorted(files),
        max_workers=4,
    )
    completed = []
    for filename, size in sorted(files.items()):
        path = destination / filename
        if path.stat().st_size != size:
            raise ValueError("downloaded component size mismatch")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        completed.append({"name": filename, "bytes": size, "sha256": checksum})
    metadata = {
        "name": name,
        "repository": repo,
        "revision": revision,
        "source": f"https://huggingface.co/{repo}/tree/{revision}",
        "bytes": expected_bytes,
        "completed_utc": datetime.now(UTC).isoformat(),
        "files": completed,
    }
    (destination / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"status": "ready", "name": name, "bytes": expected_bytes}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--deadline", required=True, help="Absolute ISO-8601 UTC stop time")
    parser.add_argument("--name", choices=CANDIDATES)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.worker:
        try:
            download_candidate(args.name, root)
        except Exception as exc:
            print(
                json.dumps(
                    {"status": "failed", "name": args.name, "error_type": type(exc).__name__}
                )
            )
            return 1
        return 0
    deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        parser.error("deadline must include a UTC offset")

    def run(name: str) -> int:
        seconds = (deadline - datetime.now(UTC)).total_seconds()
        if seconds <= 0:
            return 2
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--root",
            str(root),
            "--deadline",
            args.deadline,
            "--name",
            name,
            "--worker",
        ]
        try:
            return subprocess.run(command, timeout=seconds, check=False).returncode
        except subprocess.TimeoutExpired:
            print(json.dumps({"status": "deadline_reached", "name": name}), flush=True)
            return 2

    names = [args.name] if args.name else list(CANDIDATES)
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(run, names))
    return max(outcomes)


if __name__ == "__main__":
    raise SystemExit(main())
