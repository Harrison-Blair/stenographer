# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``pw-record`` stdout decoder: raw little-endian (PipeWire 1.0) and AU (PipeWire 1.6)."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from stenographer.lib.platform.errors import PwRecordFormatError
from stenographer.lib.platform.linux.pw_record import BLOCK_FRAMES, PwRecordDecoder

_SAMPLES = np.linspace(-0.9, 0.9, BLOCK_FRAMES + 100).astype(np.float32)


def _au_header(encoding: int = 6, rate: int = 16000, channels: int = 1, offset: int = 24):
    return b".snd" + struct.pack(">5I", offset, 0xFFFFFFFF, encoding, rate, channels)


def _decode(stream: bytes, piece: int) -> np.ndarray:
    decoder = PwRecordDecoder()
    blocks = []
    for start in range(0, len(stream), piece):
        blocks.extend(decoder.feed(stream[start : start + piece]))
    tail = decoder.finish()
    if tail is not None:
        blocks.append(tail)
    assert all(block.dtype == np.float32 for block in blocks)
    assert all(block.size == BLOCK_FRAMES for block in blocks[:-1])
    return np.concatenate(blocks)


@pytest.mark.parametrize("piece", [1, 3, 7, 4096])
def test_raw_little_endian_samples_are_framed_into_blocks(piece):
    audio = _decode(_SAMPLES.astype("<f4").tobytes(), piece)

    np.testing.assert_array_equal(audio, _SAMPLES)


@pytest.mark.parametrize("piece", [1, 3, 7, 4096])
def test_an_au_stream_skips_its_header_and_reads_big_endian_samples(piece):
    audio = _decode(_au_header() + _SAMPLES.astype(">f4").tobytes(), piece)

    np.testing.assert_array_equal(audio, _SAMPLES)


def test_an_au_header_with_a_longer_data_offset_skips_the_annotation():
    stream = _au_header(offset=32) + b"\0" * 8 + _SAMPLES.astype(">f4").tobytes()

    np.testing.assert_array_equal(_decode(stream, 5), _SAMPLES)


@pytest.mark.parametrize(
    "header",
    [_au_header(encoding=3), _au_header(rate=48000), _au_header(channels=2)],
    ids=["pcm16", "48k", "stereo"],
)
def test_an_au_stream_of_another_format_is_an_error(header):
    with pytest.raises(PwRecordFormatError):
        PwRecordDecoder().feed(header)


def test_a_stream_that_ends_inside_a_sample_is_an_error():
    decoder = PwRecordDecoder()
    decoder.feed(b"\0\0\0\0\0\0")

    with pytest.raises(PwRecordFormatError, match="middle of a float32 sample"):
        decoder.finish()


def test_discard_drops_buffered_samples_but_keeps_the_format_and_sample_alignment():
    decoder = PwRecordDecoder()
    early = np.full(10, 9.0, dtype=np.float32).astype(">f4").tobytes()
    decoder.feed(_au_header() + early + b"\x3e")
    decoder.discard()

    rest = _SAMPLES.astype(">f4").tobytes()
    blocks = decoder.feed(b"\x80\0\0" + rest)
    tail = decoder.finish()

    audio = np.concatenate([*blocks, tail])
    assert audio[0] == np.float32(0.25)
    np.testing.assert_array_equal(audio[1:], _SAMPLES)


def _with_non_finite() -> np.ndarray:
    """``_SAMPLES`` with NaN, +infinity, and -infinity between finite samples, in two blocks."""
    samples = _SAMPLES.copy()
    samples[[3, 300, BLOCK_FRAMES + 7]] = [np.nan, np.inf, -np.inf]
    return samples


@pytest.mark.parametrize(
    "encode",
    [
        lambda samples: samples.astype("<f4").tobytes(),
        lambda samples: _au_header() + samples.astype(">f4").tobytes(),
    ],
    ids=["raw", "au"],
)
def test_non_finite_samples_become_zero_and_are_counted(encode):
    decoder = PwRecordDecoder()
    blocks = decoder.feed(encode(_with_non_finite()))
    audio = np.concatenate([*blocks, decoder.finish()])

    expected = _SAMPLES.copy()
    expected[[3, 300, BLOCK_FRAMES + 7]] = 0.0
    np.testing.assert_array_equal(audio, expected)
    assert decoder.replaced == 3


def test_a_stream_of_finite_samples_replaces_nothing():
    decoder = PwRecordDecoder()
    blocks = decoder.feed(_SAMPLES.astype("<f4").tobytes())
    audio = np.concatenate([*blocks, decoder.finish()])

    np.testing.assert_array_equal(audio, _SAMPLES)
    assert decoder.replaced == 0
