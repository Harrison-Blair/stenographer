# SPDX-License-Identifier: GPL-3.0-or-later
"""Host checks and audio feeding of the NeMo-Speech speaker runtime."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile

from stenographer.lib.platform.errors import SpeakerDiarizerError
from stenographer.lib.platform.linux import nemo_diarizer
from stenographer.lib.platform.linux.nemo_diarizer import NemoSpeakerDiarizer, file_blocks
from stenographer.lib.platform.linux.nemo_speech import (
    C_LIBRARY,
    NO_AVX2,
    has_avx2,
    runtime_dir,
    unavailable_reason,
)

WITH_AVX2 = (
    "processor\t: 0\nflags\t\t: fpu sse2 avx avx2 fma\n\nprocessor\t: 1\nflags\t\t: fpu avx2\n"
)
WITHOUT_AVX2 = "processor\t: 0\nflags\t\t: fpu sse2 sse4_2 avx\n"


def test_avx2_needs_the_flag_on_every_cpu() -> None:
    assert has_avx2(WITH_AVX2)
    assert not has_avx2(WITHOUT_AVX2)
    assert not has_avx2(WITH_AVX2 + "processor\t: 2\nflags\t\t: fpu sse2\n")
    assert not has_avx2("")


def test_avx2_flag_must_match_a_whole_word() -> None:
    assert not has_avx2("flags\t\t: avx2_fake avx512f\n")


def test_x86_64_without_avx2_is_unavailable() -> None:
    assert unavailable_reason("x86_64", WITHOUT_AVX2, True, True) == NO_AVX2


def test_x86_64_with_avx2_and_files_is_available() -> None:
    assert unavailable_reason("x86_64", WITH_AVX2, True, True) is None


def test_aarch64_needs_no_cpu_flags() -> None:
    assert unavailable_reason("aarch64", "", True, True) is None


def test_missing_runtime_or_model_is_unavailable() -> None:
    assert "riscv64" in unavailable_reason("riscv64", "", False, True)
    assert "model" in unavailable_reason("x86_64", WITH_AVX2, True, False)


@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
def test_runtime_ships_for_both_linux_architectures(machine: str) -> None:
    assert (runtime_dir(machine) / C_LIBRARY).is_file()


def test_no_avx2_raises_before_any_helper_starts(monkeypatch) -> None:
    monkeypatch.setattr(nemo_diarizer, "host_unavailable_reason", lambda: NO_AVX2)
    diarizer = NemoSpeakerDiarizer(threads=2)

    assert diarizer.unavailable_reason() == NO_AVX2
    with pytest.raises(SpeakerDiarizerError, match="AVX2"):
        diarizer.open_live("mic")
    with pytest.raises(SpeakerDiarizerError, match="AVX2"):
        diarizer.diarize_file(np.zeros(16000, np.float32))
    assert diarizer.pid is None


def test_samples_are_fed_in_blocks_with_progress() -> None:
    samples = np.arange(16000 * 5, dtype=np.float32)

    blocks = list(file_blocks(samples, 2.0))

    assert [len(block) for block, _, _ in blocks] == [32000, 32000, 16000]
    assert {rate for _, rate, _ in blocks} == {16000}
    assert [done for _, _, done in blocks] == [0.4, 0.8, 1.0]
    assert np.array_equal(np.concatenate([block for block, _, _ in blocks]), samples)


def test_file_is_fed_as_mono_at_its_own_rate(tmp_path: Path) -> None:
    left = np.full(48000 * 3, 0.5, np.float32)
    right = np.zeros(48000 * 3, np.float32)
    path = tmp_path / "stereo.flac"
    soundfile.write(path, np.stack([left, right], axis=1), 48000)

    blocks = list(file_blocks(path, 2.0))

    assert [len(block) for block, _, _ in blocks] == [96000, 48000]
    assert {rate for _, rate, _ in blocks} == {48000}
    assert blocks[-1][2] == 1.0
    assert all(block.ndim == 1 and block.dtype == np.float32 for block, _, _ in blocks)
    assert np.allclose(blocks[0][0], 0.25, atol=1e-3)
