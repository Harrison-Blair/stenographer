#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download the configured ASR model with progress reporting."""

import argparse
import sys
import time

from huggingface_hub import snapshot_download


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the stenographer ASR model.")
    parser.add_argument(
        "--repo-id",
        default="Systran/faster-whisper-medium.en",
        help="Hugging Face repo id to download (default: %(default)s)",
    )
    args = parser.parse_args()

    print(f"Downloading {args.repo_id} ...", flush=True)
    start = time.monotonic()
    path = snapshot_download(
        repo_id=args.repo_id,
        allow_patterns=[
            "*.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.txt",
            "preprocessor_config.json",
            "config.json",
        ],
    )
    elapsed = time.monotonic() - start
    print(f"Downloaded to {path} in {elapsed:.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
