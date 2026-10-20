# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit live-model downloads: hashes, skip behavior, and cleanup."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from stenographer.lib.live import download
from stenographer.lib.live.errors import LiveDownloadError
from stenographer.lib.live.models import LiveModel


def test_download_writes_files_only_after_hash_validation(tmp_path):
    models = (
        LiveModel("vad.onnx", "https://example.test/vad.onnx", hashlib.sha256(b"vad").hexdigest()),
        LiveModel(
            "speaker.onnx",
            "https://example.test/speaker.onnx",
            hashlib.sha256(b"speaker").hexdigest(),
        ),
    )
    payloads = {"vad.onnx": b"vad", "speaker.onnx": b"speaker"}

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(payloads[Path(url).name])

    downloaded = download.download_live_models(tmp_path, fetch=fetch, models=models)

    assert set(downloaded) == {model.filename for model in models}
    for model in models:
        path = tmp_path / "models" / "live" / model.filename
        assert path.read_bytes() == payloads[model.filename]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == model.sha256


def test_download_skips_a_present_file_with_the_pinned_hash(tmp_path):
    content = b"live model test payload"
    model = LiveModel(
        "vad.onnx", "https://example.test/vad.onnx", hashlib.sha256(content).hexdigest()
    )
    model_dir = tmp_path / "models" / "live"
    model_dir.mkdir(parents=True)
    destination = model_dir / model.filename
    destination.write_bytes(content)

    def fail_if_called(url: str, path: Path) -> None:
        pytest.fail("a valid existing model must not be fetched again")

    assert download.download_live_models(tmp_path, fetch=fail_if_called, models=(model,)) == ()
    assert destination.read_bytes() == content


def test_bad_download_hash_fails_and_removes_temporary_file(tmp_path):
    model = LiveModel(
        "vad.onnx", "https://example.test/vad.onnx", hashlib.sha256(b"right").hexdigest()
    )

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(b"wrong model data")

    with pytest.raises(LiveDownloadError, match="SHA-256"):
        download.download_live_models(tmp_path, fetch=fetch, models=(model,))

    model_dir = tmp_path / "models" / "live"
    assert not (model_dir / model.filename).exists()
    assert list(model_dir.iterdir()) == []


def test_fetch_failure_removes_temporary_file(tmp_path):
    model = LiveModel("vad.onnx", "https://example.test/vad.onnx", "unused")

    def fail_after_partial_write(url: str, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("network interrupted")

    with pytest.raises(LiveDownloadError, match="network interrupted"):
        download.download_live_models(tmp_path, fetch=fail_after_partial_write, models=(model,))

    model_dir = tmp_path / "models" / "live"
    assert list(model_dir.iterdir()) == []
