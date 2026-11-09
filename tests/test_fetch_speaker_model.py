# SPDX-License-Identifier: GPL-3.0-or-later
"""The build-time speaker-model fetch keeps a pinned file and rejects any other."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_speaker_model import PinMismatchError, fetch

_CONTENT = b"GGUF test model bytes"
_SHA256 = hashlib.sha256(_CONTENT).hexdigest()


def _source(tmp_path: Path) -> str:
    source = tmp_path / "source.gguf"
    source.write_bytes(_CONTENT)
    return source.as_uri()


def test_download_matching_the_pin_lands_at_dest(tmp_path: Path) -> None:
    dest = tmp_path / "models" / "model.gguf"

    assert fetch(_source(tmp_path), dest, len(_CONTENT), _SHA256) is True
    assert dest.read_bytes() == _CONTENT
    assert not dest.with_name("model.gguf.part").exists()


def test_cached_file_is_kept_without_download(tmp_path: Path) -> None:
    dest = tmp_path / "model.gguf"
    dest.write_bytes(_CONTENT)

    assert fetch((tmp_path / "missing.gguf").as_uri(), dest, len(_CONTENT), _SHA256) is False


def test_wrong_sha256_fails_and_leaves_no_file(tmp_path: Path) -> None:
    dest = tmp_path / "model.gguf"

    with pytest.raises(PinMismatchError):
        fetch(_source(tmp_path), dest, len(_CONTENT), "0" * 64)
    assert not dest.exists()
    assert not dest.with_name("model.gguf.part").exists()


def test_wrong_size_fails(tmp_path: Path) -> None:
    dest = tmp_path / "model.gguf"

    with pytest.raises(PinMismatchError):
        fetch(_source(tmp_path), dest, len(_CONTENT) + 1, _SHA256)
    assert not dest.exists()


def test_corrupt_cached_file_is_replaced(tmp_path: Path) -> None:
    dest = tmp_path / "model.gguf"
    dest.write_bytes(b"truncated")

    assert fetch(_source(tmp_path), dest, len(_CONTENT), _SHA256) is True
    assert dest.read_bytes() == _CONTENT
