# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the deterministic procedural sound-pack renderer."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import wave
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cue_audition import (
    CUE_ORDER,
    FAMILY_ORDER,
    GENERATOR_VERSION,
    CueAuditionError,
    generate_output,
    render_cue,
    verify_output,
    verify_packaged,
)


class _DecodedWav(NamedTuple):
    channels: int
    sample_width: int
    sample_rate: int
    compression: str
    frame_count: int
    samples: tuple[int, ...]


def _read_wav(data: bytes) -> _DecodedWav:
    with wave.open(BytesIO(data), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        return _DecodedWav(
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getcomptype(),
            wav.getnframes(),
            samples,
        )


def _peak_dbfs(samples: tuple[int, ...]) -> float:
    peak = max(map(abs, samples), default=0) / 32768.0
    return 20.0 * math.log10(peak) if peak else -math.inf


def test_all_twelve_cues_are_valid_short_pcm_with_clean_endpoints() -> None:
    rendered = {
        (family, cue): render_cue(family, cue) for family in FAMILY_ORDER for cue in CUE_ORDER
    }

    assert set(rendered) == {
        (family, cue)
        for family in ("warm-desk", "soft-electronic", "minimal-ui")
        for cue in ("record_start", "record_stop", "delivered", "error")
    }
    for data in rendered.values():
        decoded = _read_wav(data)
        assert decoded.channels == 1
        assert decoded.sample_width == 2
        assert decoded.sample_rate == 48_000
        assert decoded.compression == "NONE"
        assert 0 < decoded.frame_count < 0.3 * decoded.sample_rate
        assert any(decoded.samples)
        assert decoded.samples[0] == decoded.samples[-1] == 0
        assert abs(sum(decoded.samples) / len(decoded.samples)) <= 1.0
        assert _peak_dbfs(decoded.samples) <= -12.0


def test_family_level_and_duration_hierarchy() -> None:
    for family in FAMILY_ORDER:
        decoded = {cue: _read_wav(render_cue(family, cue)) for cue in CUE_ORDER}
        durations = {cue: wav.frame_count / wav.sample_rate for cue, wav in decoded.items()}
        peaks = {cue: _peak_dbfs(wav.samples) for cue, wav in decoded.items()}

        assert durations["record_start"] == min(durations.values())
        assert peaks["record_start"] == min(peaks.values())
        for routine in ("record_start", "record_stop", "delivered"):
            assert peaks["error"] - peaks[routine] <= 3.0


def test_generation_is_byte_identical_and_manifested(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_output(first, FAMILY_ORDER)
    generate_output(second, FAMILY_ORDER)

    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert len(first_files) == 13
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator"]["version"] == GENERATOR_VERSION
    assert manifest["source"]["license"] == "GPL-3.0-or-later"
    assert manifest["source"]["external_audio_samples_incorporated"] is False
    assert set(manifest["families"]) == set(FAMILY_ORDER)
    assert set(manifest["family_descriptions"]) == set(FAMILY_ORDER)
    for family in FAMILY_ORDER:
        assert set(manifest["families"][family]) == set(CUE_ORDER)
        for cue in CUE_ORDER:
            entry = manifest["families"][family][cue]
            assert entry["duration_ms"] < 300.0
            assert entry["peak_dbfs"] <= -12.0
            assert entry["rms_dbfs"] < entry["peak_dbfs"]
            path = first / entry["path"]
            assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_byte_verifier_detects_changed_output(tmp_path: Path) -> None:
    generate_output(tmp_path, ("warm-desk",))
    verify_output(tmp_path, ("warm-desk",))

    path = tmp_path / "warm-desk" / "record_stop.wav"
    path.write_bytes(path.read_bytes() + b"changed")

    with pytest.raises(CueAuditionError, match="byte mismatch"):
        verify_output(tmp_path, ("warm-desk",))


def test_packaged_generated_packs_are_byte_identical_to_fresh_renders() -> None:
    verify_packaged(FAMILY_ORDER)
