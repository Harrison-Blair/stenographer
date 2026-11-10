# SPDX-License-Identifier: GPL-3.0-or-later
"""Download the pinned Nemotron-3-Diarization GGUF into the package assets.

``scripts/build.sh`` runs this before PyInstaller. The file is git-ignored and is
never committed (it is larger than GitHub's file limit). A file that is already
present with the pinned size and sha256 is kept, so a rebuild does not download
again. Any size or sha256 mismatch after a download is an error.

    python -I scripts/fetch_speaker_model.py [DEST]
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://huggingface.co/nvidia/Nemotron-3-Diarization/resolve/"
    "f667ed73aee57d40cc39428eb768b4fd87a0a29e/Nemotron-3-Diarization.q8_0.gguf"
)
SIZE = 107_012_128
SHA256 = "08456d9e22cd9a323c0364d98375f3746d6e68507ebb705cd46438c534c7a3a1"
DEST = (
    Path(__file__).resolve().parent.parent
    / "src/stenographer/assets/models/Nemotron-3-Diarization.q8_0.gguf"
)
_BLOCK = 1 << 20


class PinMismatchError(RuntimeError):
    """The file does not have the pinned size or sha256."""


def file_matches(path: Path, size: int, sha256: str) -> bool:
    """True when *path* has exactly *size* bytes and the *sha256* digest."""
    if path.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest() == sha256


def fetch(url: str, dest: Path, size: int, sha256: str) -> bool:
    """Make *dest* the pinned file. Return True when it was downloaded.

    Raise ``PinMismatchError`` when the download does not match the pin; the
    partial file is removed and *dest* is left unchanged.
    """
    if dest.exists() and file_matches(dest, size, sha256):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
            while block := response.read(_BLOCK):
                out.write(block)
        if not file_matches(partial, size, sha256):
            raise PinMismatchError(f"{url} does not match the pin ({size} bytes, sha256 {sha256})")
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return True


def main(argv: list[str]) -> int:
    dest = Path(argv[0]) if argv else DEST
    try:
        downloaded = fetch(URL, dest, SIZE, SHA256)
    except (OSError, PinMismatchError) as exc:
        print(f"error: speaker model: {exc}", file=sys.stderr)
        return 1
    print(f"speaker model {'downloaded' if downloaded else 'cached'}: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
