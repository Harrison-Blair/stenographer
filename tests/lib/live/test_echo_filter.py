# SPDX-License-Identifier: GPL-3.0-or-later
"""Echo filter: pairing of microphone and system samples, and the real canceller."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from stenographer.lib.live.echo_filter import EchoFilter, clean_file

RATE = 16000
FRAME = 160


def _subtract(mic, system):
    """A canceller that shows which system samples each microphone sample got."""
    return mic - system


def _ramp(first, count):
    return np.arange(first, first + count, dtype=np.float32)


def _filter(**options):
    echo = EchoFilter(_subtract, **options)
    echo.start("mic", 0)
    return echo


def _joined(chunks):
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


def test_a_block_goes_on_at_once_while_the_system_source_does_not_run():
    echo = _filter()
    block = _ramp(1, FRAME)

    assert [chunk.tolist() for chunk in echo.mic(block)] == [block.tolist()]
    assert (echo.cleaned_samples, echo.raw_samples) == (0, 0)


def test_a_block_is_cleaned_with_the_system_samples_of_its_position():
    echo = _filter()
    echo.start("system", 0)

    assert echo.system(_ramp(1000, 2 * FRAME)) == []
    first = echo.mic(_ramp(0, FRAME))
    second = echo.mic(_ramp(FRAME, FRAME))

    # Position p of the microphone gets position p of the system: p - (1000 + p).
    assert _joined(first).tolist() == [-1000.0] * FRAME
    assert _joined(second).tolist() == [-1000.0] * FRAME
    assert (echo.cleaned_samples, echo.raw_samples) == (2 * FRAME, 0)


def test_a_block_waits_until_its_system_samples_arrive():
    echo = _filter()
    echo.start("system", 0)

    assert echo.mic(_ramp(0, FRAME)) == []
    assert echo.system(_ramp(1000, FRAME // 2)) == []
    ready = echo.system(_ramp(1000 + FRAME // 2, FRAME // 2))

    assert _joined(ready).tolist() == [-1000.0] * FRAME


def test_the_canceller_gets_whole_frames_from_blocks_of_another_size():
    calls = []

    def cancel(mic, system):
        calls.append(mic.size)
        return mic - system

    echo = EchoFilter(cancel)
    echo.start("mic", 0)
    echo.start("system", 0)
    echo.system(_ramp(1000, 3 * 512))
    ready = [chunk for start in (0, 512, 1024) for chunk in echo.mic(_ramp(start, 512))]

    assert calls == [480, 480, 480]
    assert _joined(ready).tolist() == [-1000.0] * 1440
    # The last part of a frame comes out when the microphone stops, not cleaned.
    assert _joined(echo.stop("mic")).tolist() == _ramp(1440, 96).tolist()
    assert (echo.cleaned_samples, echo.raw_samples) == (1440, 96)


def test_a_block_goes_on_raw_when_the_wait_passes_the_limit():
    echo = _filter(hold_seconds=2 * FRAME / RATE)
    echo.start("system", 0)

    assert echo.mic(_ramp(0, FRAME)) == []
    assert echo.mic(_ramp(FRAME, FRAME)) == []
    late = echo.mic(_ramp(2 * FRAME, FRAME))

    assert _joined(late).tolist() == _ramp(0, FRAME).tolist()
    assert echo.raw_samples == FRAME
    # The system samples of the block that went on are not used for a later block.
    ready = echo.system(_ramp(1000, 3 * FRAME))
    assert _joined(ready).tolist() == [-1000.0] * (2 * FRAME)


def test_a_system_run_that_starts_later_is_paired_from_its_start_position():
    echo = _filter()
    assert len(echo.mic(_ramp(0, FRAME))) == 1

    echo.start("system", FRAME)
    assert echo.mic(_ramp(FRAME, FRAME)) == []
    ready = echo.system(_ramp(5000, FRAME))

    # Microphone position 160 gets the first sample of the system run.
    assert _joined(ready).tolist() == (_ramp(FRAME, FRAME) - _ramp(5000, FRAME)).tolist()


@pytest.mark.parametrize("source", ["mic", "system"])
def test_the_end_of_a_run_sends_the_waiting_blocks_on_raw_in_order(source):
    echo = _filter()
    echo.start("system", 0)
    echo.mic(_ramp(0, FRAME))
    echo.mic(_ramp(FRAME, FRAME))

    released = echo.stop(source)

    assert _joined(released).tolist() == _ramp(0, 2 * FRAME).tolist()
    assert echo.raw_samples == 2 * FRAME
    assert echo.stop(source) == []


def test_the_microphone_goes_on_at_once_after_the_system_run_ends():
    echo = _filter()
    echo.start("system", 0)
    echo.stop("system")

    assert len(echo.mic(_ramp(0, FRAME))) == 1


def test_system_samples_that_no_block_used_are_dropped_after_two_seconds():
    echo = _filter()
    echo.start("system", 0)
    for second in range(5):
        echo.system(_ramp(second * RATE, RATE))

    # Position 1 s is older than the last 2 s of system samples: no pair for it.
    echo.start("mic", RATE)
    old = echo.mic(_ramp(0, FRAME))
    # Position 4 s is in the last 2 s: it gets the system sample of that position.
    echo.start("mic", 4 * RATE)
    new = echo.mic(_ramp(0, FRAME))

    assert _joined(old).tolist() == _ramp(0, FRAME).tolist()
    assert _joined(new).tolist() == (_ramp(0, FRAME) - _ramp(4 * RATE, FRAME)).tolist()


def _through_filter(mic, system):
    """Run the real canceller on blocks of the live capture size."""
    echo = EchoFilter()
    echo.start("mic", 0)
    echo.start("system", 0)
    chunks = []
    for start in range(0, mic.size, 512):
        chunks += echo.system(system[start : start + 512])
        chunks += echo.mic(mic[start : start + 512])
    chunks += echo.stop("mic")
    return np.concatenate(chunks)


def _level_db(samples):
    return 10 * np.log10(np.mean(np.square(samples)))


# The canceller needs some seconds to learn the echo path; its output is 8 ms late.
_SETTLED = slice(6 * RATE, 12 * RATE - 200)
_SETTLED_OUT = slice(6 * RATE + 128, 12 * RATE - 200 + 128)


def test_the_real_canceller_removes_an_echo_of_the_system_audio():
    rng = np.random.default_rng(1)
    system = (rng.standard_normal(12 * RATE) * 0.05).astype(np.float32)
    echo = np.zeros_like(system)
    echo[1600:] = 0.5 * system[:-1600]

    cleaned = _through_filter(echo, system)

    assert cleaned.size == echo.size
    # Measured: 14.6 dB less.
    assert _level_db(cleaned[_SETTLED_OUT]) < _level_db(echo[_SETTLED]) - 10


def test_the_real_canceller_keeps_sound_that_is_not_in_the_system_audio():
    rng = np.random.default_rng(1)
    system = (rng.standard_normal(12 * RATE) * 0.05).astype(np.float32)
    room = (rng.standard_normal(12 * RATE) * 0.03).astype(np.float32)

    cleaned = _through_filter(room, system)

    # Measured: correlation 0.98, level change 0.1 dB.
    assert np.corrcoef(room[_SETTLED], cleaned[_SETTLED_OUT])[0, 1] > 0.95
    assert abs(_level_db(cleaned[_SETTLED_OUT]) - _level_db(room[_SETTLED])) < 1


def _write(path, samples):
    sf.write(path, samples, RATE, format="FLAC", subtype="PCM_24")


def test_clean_file_pairs_by_position_and_copies_the_microphone_after_the_system_end(tmp_path):
    # More than one read of the file, and a system file that ends inside a frame.
    count = 11 * RATE + 77
    mic = np.full(count, 0.5, dtype=np.float32)
    system_count = 10 * RATE + 4 * FRAME + 30
    system = np.full(system_count, 0.25, dtype=np.float32)
    _write(tmp_path / "mic.flac", mic)
    _write(tmp_path / "system.flac", system)

    clean_file(tmp_path / "mic.flac", tmp_path / "system.flac", tmp_path / "out.flac", _subtract)

    cleaned, rate = sf.read(tmp_path / "out.flac", dtype="float32")
    paired = 10 * RATE + 4 * FRAME
    assert rate == RATE
    assert cleaned.size == count
    assert np.allclose(cleaned[:paired], 0.25, atol=1e-4)
    assert np.allclose(cleaned[paired:], 0.5, atol=1e-4)


def test_clean_file_refuses_audio_that_is_not_16_khz_mono(tmp_path):
    _write(tmp_path / "mic.flac", np.zeros(RATE, dtype=np.float32))
    sf.write(tmp_path / "system.flac", np.zeros(RATE, dtype=np.float32), 48000, format="FLAC")

    with pytest.raises(ValueError, match="mono at 16000 Hz"):
        clean_file(tmp_path / "mic.flac", tmp_path / "system.flac", tmp_path / "out.flac")
