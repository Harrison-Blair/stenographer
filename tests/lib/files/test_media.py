# SPDX-License-Identifier: GPL-3.0-or-later
"""Supported media probing and decoding for Files jobs."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np
import soundfile

from stenographer.lib.files.media import decode_media, inspect_media
from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder


def test_soundfile_media_is_downmixed_and_resampled(tmp_path):
    path = tmp_path / "short.wav"
    samples = np.column_stack(
        (np.linspace(-0.5, 0.5, 4800, dtype=np.float32), np.zeros(4800, dtype=np.float32))
    )
    soundfile.write(path, samples, 48000)
    decoder = SubprocessFfmpegDecoder()

    info = inspect_media(path, decoder)
    decoded = decode_media(path, info, decoder)

    assert info.duration_seconds == 0.1
    assert info.sample_rate == 48000
    assert info.channels == 2
    assert not info.uses_ffmpeg
    assert decoded.sample_rate == 16000
    assert abs(decoded.samples.size - 1600) <= 40
    assert decoded.samples.dtype == np.float32
    assert np.max(np.abs(decoded.samples)) > 0.2


def test_m4a_uses_ffmpeg_even_if_soundfile_reports_support(tmp_path, monkeypatch):
    class Decoder:
        def available(self):
            return True

        def duration(self, _path):
            return 0.25

        def decode(self, _path, *, block_frames=65536):
            return iter(())

    info_calls = []

    def soundfile_info(source):
        info_calls.append(source)
        return SimpleNamespace(samplerate=16000, channels=1, frames=4000)

    monkeypatch.setattr("stenographer.lib.files.media.soundfile.info", soundfile_info)

    for suffix in (".m4a", ".aac"):
        path = tmp_path / f"recording{suffix}"
        path.touch()
        info = inspect_media(path, Decoder())
        assert info.uses_ffmpeg
        assert info.duration_seconds == 0.25
    assert info_calls == []


def test_unsupported_media_uses_ffmpeg_float32_output(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable = binary_dir / "ffmpeg"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import struct, sys\n"
        "sys.stdout.buffer.write(struct.pack('<3f', -0.25, 0.125, 0.75))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    path = tmp_path / "unsupported.m4a"
    path.touch()
    decoder = SubprocessFfmpegDecoder()

    info = inspect_media(path, decoder)
    decoded = decode_media(path, info, decoder)

    assert info.uses_ffmpeg
    assert not info.needs_ffmpeg
    assert decoded.sample_rate == 16000
    np.testing.assert_array_equal(decoded.samples, [-0.25, 0.125, 0.75])


def test_unsupported_media_reports_needs_ffmpeg_when_binary_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    path = tmp_path / "unsupported.m4a"
    path.touch()

    info = inspect_media(path, SubprocessFfmpegDecoder())

    assert info.needs_ffmpeg
    assert info.uses_ffmpeg
    assert info.duration_seconds is None
