# SPDX-License-Identifier: GPL-3.0-or-later
"""System ffmpeg decoding through the platform adapter."""

from __future__ import annotations

import os
import sys

import numpy as np

from stenographer.lib.platform.linux.ffmpeg_decoder import SubprocessFfmpegDecoder


def _fake_ffmpeg(directory, tmp_path):
    executable = directory / "ffmpeg"
    arguments = tmp_path / "ffmpeg-args.txt"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, struct, sys\n"
        f"pathlib.Path({str(arguments)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "sys.stdout.buffer.write(struct.pack('<4f', -0.5, 0.0, 0.25, 1.0))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return arguments


def test_ffmpeg_decoder_uses_the_system_binary_and_reads_float32_pipe(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    arguments = _fake_ffmpeg(binary_dir, tmp_path)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    source = tmp_path / "audio.m4a"
    source.touch()
    decoder = SubprocessFfmpegDecoder()

    blocks = tuple(decoder.decode(source, block_frames=2))

    np.testing.assert_array_equal(np.concatenate(blocks), [-0.5, 0.0, 0.25, 1.0])
    assert [len(block) for block in blocks] == [2, 2]
    assert arguments.read_text(encoding="utf-8").split() == [
        "-nostdin",
        "-i",
        str(source),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-",
    ]


def test_ffmpeg_availability_uses_path(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    _fake_ffmpeg(binary_dir, tmp_path)
    monkeypatch.setenv("PATH", str(binary_dir))

    assert SubprocessFfmpegDecoder().available()


def test_ffmpeg_duration_reads_ffprobe_result(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable = binary_dir / "ffprobe"
    executable.write_text(f"#!{sys.executable}\nprint('12.5')\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")

    assert SubprocessFfmpegDecoder().duration(tmp_path / "audio.m4a") == 12.5
