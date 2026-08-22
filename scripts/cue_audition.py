# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate, verify, and audition original procedural sound-pack cues.

This is development tooling, deliberately separate from production playback.
All generated audio is synthesized here; no external samples are loaded or
incorporated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import struct
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

GENERATOR_VERSION = "1.0.0"
SAMPLE_RATE = 48_000
SAMPLE_WIDTH_BYTES = 2
DEFAULT_VOLUME = 0.6
DEFAULT_OUTPUT_DIRECTORY = Path("build/cue-audition")
PACKAGED_SOUND_DIRECTORY = Path(__file__).resolve().parents[1] / "src/stenographer/assets/sounds"
PEAK_CEILING_DBFS = -12.0

FAMILY_ORDER = ("warm-desk", "soft-electronic", "minimal-ui")
CUE_ORDER = ("record_start", "record_stop", "delivered", "error")

_FAMILY_DESCRIPTIONS = {
    "warm-desk": "Felted impacts, paper brushes, and softly resonant wooden bodies.",
    "soft-electronic": "Rounded sine and triangle layers with gentle pitch movement.",
    "minimal-ui": "Restrained, mostly nonmusical soft clicks and muted plucks.",
}

_DURATION_MS = {
    "record_start": 72,
    "record_stop": 128,
    "delivered": 208,
    "error": 246,
}
_TARGET_PEAK_DBFS = {
    "record_start": -17.0,
    "record_stop": -16.3,
    "delivered": -15.4,
    "error": -14.2,
}
_SEEDS = {
    (family, cue): 10_000 + family_index * 100 + cue_index
    for family_index, family in enumerate(FAMILY_ORDER)
    for cue_index, cue in enumerate(CUE_ORDER)
}
_WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")
_CUE_PAUSE_SECONDS = 0.45
_FAMILY_PAUSE_SECONDS = 0.9


class CueAuditionError(ValueError):
    """The requested cue operation cannot be completed safely."""


def _add(target: list[float], source: Sequence[float], start: int = 0, gain: float = 1.0) -> None:
    available = max(0, len(target) - start)
    for index, sample in enumerate(source[:available]):
        target[start + index] += gain * sample


def _filtered_noise(
    count: int, seed: int, cutoff_hz: float, *, highpass: bool = False
) -> list[float]:
    rng = random.Random(seed)
    coefficient = 1.0 - math.exp(-2.0 * math.pi * cutoff_hz / SAMPLE_RATE)
    low = 0.0
    output: list[float] = []
    for _ in range(count):
        white = rng.uniform(-1.0, 1.0)
        low += coefficient * (white - low)
        output.append(white - low if highpass else low)
    return output


def _tone(
    count: int,
    start_hz: float,
    end_hz: float,
    decay_seconds: float,
    *,
    triangle: float = 0.0,
    attack_seconds: float = 0.003,
    phase_offset: float = 0.0,
) -> list[float]:
    phase = phase_offset
    output: list[float] = []
    denominator = max(1, count - 1)
    for index in range(count):
        progress = index / denominator
        frequency = start_hz + (end_hz - start_hz) * progress
        phase += 2.0 * math.pi * frequency / SAMPLE_RATE
        sine = math.sin(phase)
        triangle_wave = 2.0 / math.pi * math.asin(sine)
        attack = 1.0 - math.exp(-(index / SAMPLE_RATE) / attack_seconds)
        decay = math.exp(-(index / SAMPLE_RATE) / decay_seconds)
        output.append((sine * (1.0 - triangle) + triangle_wave * triangle) * attack * decay)
    return output


def _warm_hit(count: int, seed: int, low_hz: float, high_hz: float) -> list[float]:
    body = _tone(count, low_hz, low_hz * 0.92, 0.038, triangle=0.12, attack_seconds=0.001)
    upper = _tone(
        count,
        high_hz,
        high_hz * 0.96,
        0.024,
        triangle=0.08,
        attack_seconds=0.001,
        phase_offset=0.7,
    )
    felt = _filtered_noise(count, seed, 1_100.0)
    return [
        (0.62 * body[index] + 0.25 * upper[index] + 0.32 * felt[index])
        * math.exp(-(index / SAMPLE_RATE) / 0.032)
        for index in range(count)
    ]


def _paper_brush(count: int, seed: int, decay_seconds: float) -> list[float]:
    noise = _filtered_noise(count, seed, 1_800.0, highpass=True)
    smoothed = _filtered_noise(count, seed + 37, 4_200.0)
    output: list[float] = []
    for index in range(count):
        seconds = index / SAMPLE_RATE
        attack = 1.0 - math.exp(-seconds / 0.004)
        output.append(
            (0.65 * noise[index] + 0.35 * smoothed[index])
            * attack
            * math.exp(-seconds / decay_seconds)
        )
    return output


def _warm_desk(cue: str, count: int, seed: int) -> list[float]:
    output = [0.0] * count
    if cue == "record_start":
        _add(output, _warm_hit(count, seed, 185.0, 315.0), gain=0.72)
    elif cue == "record_stop":
        _add(output, _paper_brush(count, seed, 0.055), gain=0.34)
        _add(
            output,
            _warm_hit(count, seed + 1, 155.0, 270.0),
            start=int(0.018 * SAMPLE_RATE),
            gain=0.8,
        )
    elif cue == "delivered":
        _add(output, _paper_brush(count, seed, 0.075), gain=0.25)
        _add(output, _warm_hit(count, seed + 1, 215.0, 355.0), gain=0.56)
        _add(
            output,
            _warm_hit(count, seed + 2, 270.0, 440.0),
            start=int(0.070 * SAMPLE_RATE),
            gain=0.62,
        )
    else:
        _add(output, _paper_brush(count, seed, 0.095), gain=0.3)
        _add(output, _warm_hit(count, seed + 1, 135.0, 225.0), gain=0.8)
        _add(
            output,
            _warm_hit(count, seed + 2, 118.0, 195.0),
            start=int(0.092 * SAMPLE_RATE),
            gain=0.88,
        )
    return output


def _soft_voice(
    count: int,
    start_hz: float,
    end_hz: float,
    decay_seconds: float,
    *,
    phase_offset: float = 0.0,
) -> list[float]:
    fundamental = _tone(
        count,
        start_hz,
        end_hz,
        decay_seconds,
        triangle=0.24,
        attack_seconds=0.006,
        phase_offset=phase_offset,
    )
    overtone = _tone(
        count,
        start_hz * 2.01,
        end_hz * 2.0,
        decay_seconds * 0.58,
        triangle=0.08,
        attack_seconds=0.008,
        phase_offset=phase_offset + 0.4,
    )
    return [0.84 * fundamental[index] + 0.16 * overtone[index] for index in range(count)]


def _soft_electronic(cue: str, count: int, seed: int) -> list[float]:
    del seed  # This tonal family is deterministic without a noise source.
    output = [0.0] * count
    if cue == "record_start":
        _add(output, _soft_voice(count, 350.0, 405.0, 0.042), gain=0.78)
    elif cue == "record_stop":
        _add(output, _soft_voice(count, 430.0, 315.0, 0.072), gain=0.82)
    elif cue == "delivered":
        _add(output, _soft_voice(count, 390.0, 455.0, 0.075), gain=0.62)
        _add(
            output,
            _soft_voice(count, 505.0, 565.0, 0.082, phase_offset=0.3),
            start=int(0.066 * SAMPLE_RATE),
            gain=0.7,
        )
    else:
        _add(output, _soft_voice(count, 355.0, 245.0, 0.095), gain=0.75)
        _add(
            output,
            _soft_voice(count, 285.0, 190.0, 0.090, phase_offset=0.6),
            start=int(0.088 * SAMPLE_RATE),
            gain=0.7,
        )
    return output


def _muted_pluck(count: int, seed: int, resonance_hz: float, decay_seconds: float) -> list[float]:
    click = _filtered_noise(count, seed, 2_600.0, highpass=True)
    resonance = _tone(
        count,
        resonance_hz,
        resonance_hz * 0.9,
        decay_seconds,
        triangle=0.18,
        attack_seconds=0.0008,
        phase_offset=0.9,
    )
    return [
        0.42 * click[index] * math.exp(-(index / SAMPLE_RATE) / 0.008) + 0.58 * resonance[index]
        for index in range(count)
    ]


def _minimal_ui(cue: str, count: int, seed: int) -> list[float]:
    output = [0.0] * count
    if cue == "record_start":
        _add(output, _muted_pluck(count, seed, 760.0, 0.020), gain=0.64)
    elif cue == "record_stop":
        _add(output, _muted_pluck(count, seed, 520.0, 0.044), gain=0.72)
    elif cue == "delivered":
        _add(output, _muted_pluck(count, seed, 690.0, 0.038), gain=0.56)
        _add(
            output,
            _muted_pluck(count, seed + 1, 920.0, 0.045),
            start=int(0.058 * SAMPLE_RATE),
            gain=0.62,
        )
    else:
        _add(output, _muted_pluck(count, seed, 330.0, 0.060), gain=0.75)
        _add(
            output,
            _muted_pluck(count, seed + 1, 275.0, 0.065),
            start=int(0.086 * SAMPLE_RATE),
            gain=0.78,
        )
    return output


_SYNTHESIZERS: dict[str, Callable[[str, int, int], list[float]]] = {
    "warm-desk": _warm_desk,
    "soft-electronic": _soft_electronic,
    "minimal-ui": _minimal_ui,
}


def _finalize(samples: Sequence[float], target_peak_dbfs: float) -> bytes:
    """Remove DC, apply a two-millisecond edge fade, and quantize to PCM16."""

    count = len(samples)
    fade_count = min(round(0.002 * SAMPLE_RATE), count // 4)
    window = [1.0] * count
    for index in range(fade_count):
        gain = 0.5 - 0.5 * math.cos(math.pi * index / max(1, fade_count - 1))
        window[index] = gain
        window[-1 - index] = gain

    window_sum = sum(window)
    dc = sum(sample * gain for sample, gain in zip(samples, window, strict=True)) / window_sum
    faded = [gain * (sample - dc) for sample, gain in zip(samples, window, strict=True)]
    source_peak = max(map(abs, faded), default=0.0)
    if source_peak <= 0.0:
        raise CueAuditionError("synthesizer produced silent audio")

    target_peak = 10.0 ** (target_peak_dbfs / 20.0)
    scale = target_peak / source_peak
    pcm = [max(-32768, min(32767, round(sample * scale * 32767.0))) for sample in faded]
    pcm[0] = 0
    pcm[-1] = 0
    return struct.pack(f"<{count}h", *pcm)


def _wav_bytes(pcm: bytes) -> bytes:
    channels = 1
    block_align = channels * SAMPLE_WIDTH_BYTES
    byte_rate = SAMPLE_RATE * block_align
    header = _WAV_HEADER.pack(
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        SAMPLE_RATE,
        byte_rate,
        block_align,
        SAMPLE_WIDTH_BYTES * 8,
        b"data",
        len(pcm),
    )
    return header + pcm


def render_cue(family: str, cue: str) -> bytes:
    """Render one complete deterministic PCM WAV in memory."""

    if family not in _SYNTHESIZERS:
        raise CueAuditionError(f"unknown cue family: {family}")
    if cue not in CUE_ORDER:
        raise CueAuditionError(f"unknown cue name: {cue}")
    count = round(_DURATION_MS[cue] * SAMPLE_RATE / 1000)
    raw = _SYNTHESIZERS[family](cue, count, _SEEDS[family, cue])
    pcm = _finalize(raw, _TARGET_PEAK_DBFS[cue])
    return _wav_bytes(pcm)


def _metrics(data: bytes, relative_path: str) -> dict[str, float | int | str]:
    pcm = data[_WAV_HEADER.size :]
    if len(pcm) % SAMPLE_WIDTH_BYTES:
        raise CueAuditionError("renderer produced a misaligned PCM payload")
    sample_count = len(pcm) // SAMPLE_WIDTH_BYTES
    samples = struct.unpack(f"<{sample_count}h", pcm)
    peak = max(map(abs, samples), default=0) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / sample_count) / 32768.0
    return {
        "path": relative_path,
        "duration_ms": round(sample_count / SAMPLE_RATE * 1000.0, 3),
        "peak_dbfs": round(20.0 * math.log10(peak), 3),
        "rms_dbfs": round(20.0 * math.log10(rms), 3),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _normalize_families(families: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(families))
    if not normalized:
        raise CueAuditionError("at least one cue family is required")
    unknown = [family for family in normalized if family not in FAMILY_ORDER]
    if unknown:
        raise CueAuditionError(f"unknown cue family: {unknown[0]}")
    return normalized


def _render_families(families: Sequence[str]) -> dict[str, dict[str, bytes]]:
    return {
        family: {cue: render_cue(family, cue) for cue in CUE_ORDER}
        for family in _normalize_families(families)
    }


def _manifest(rendered: dict[str, dict[str, bytes]]) -> dict[str, object]:
    return {
        "generator": {
            "name": "stenographer-cue-audition",
            "version": GENERATOR_VERSION,
        },
        "format": {
            "container": "WAV",
            "encoding": "PCM",
            "channels": 1,
            "sample_rate_hz": SAMPLE_RATE,
            "sample_width_bits": SAMPLE_WIDTH_BYTES * 8,
        },
        "constraints": {
            "maximum_duration_ms_exclusive": 300,
            "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
            "audition_volume": DEFAULT_VOLUME,
        },
        "source": {
            "method": "original deterministic procedural synthesis",
            "license": "GPL-3.0-or-later",
            "external_audio_samples_incorporated": False,
            "statement": (
                "External sound packs were listening references only; no samples were "
                "loaded, copied, or transformed."
            ),
            "listening_references": [
                {
                    "name": "Kenney UI Audio",
                    "url": "https://kenney.nl/assets/ui-audio",
                    "use": "listening reference only",
                },
                {
                    "name": "KDE Ocean Sound Theme",
                    "url": "https://github.com/KDE/ocean-sound-theme",
                    "use": "listening reference only",
                },
            ],
        },
        "family_order": list(rendered),
        "family_descriptions": {family: _FAMILY_DESCRIPTIONS[family] for family in rendered},
        "cue_order": list(CUE_ORDER),
        "families": {
            family: {cue: _metrics(data, f"{family}/{cue}.wav") for cue, data in cues.items()}
            for family, cues in rendered.items()
        },
    }


def generate_output(output_directory: Path, families: Sequence[str]) -> Path:
    """Render selected families and write their deterministic manifest."""

    rendered = _render_families(families)
    manifest_path = output_directory / "manifest.json"
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        for family, cues in rendered.items():
            family_directory = output_directory / family
            family_directory.mkdir(parents=True, exist_ok=True)
            for cue, data in cues.items():
                (family_directory / f"{cue}.wav").write_bytes(data)

        manifest_path.write_text(
            json.dumps(_manifest(rendered), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise CueAuditionError(f"cannot write audition output: {error}") from error
    return manifest_path


def verify_output(output_directory: Path, families: Sequence[str]) -> None:
    """Re-render in memory and compare selected output WAVs byte for byte."""

    rendered = _render_families(families)
    for family, cues in rendered.items():
        for cue, expected in cues.items():
            path = output_directory / family / f"{cue}.wav"
            try:
                actual = path.read_bytes()
            except OSError as error:
                raise CueAuditionError(f"cannot read generated cue {path}: {error}") from error
            if actual != expected:
                raise CueAuditionError(f"byte mismatch: {path}")

    manifest_path = output_directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CueAuditionError(f"cannot read manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise CueAuditionError(f"manifest root is not an object: {manifest_path}")
    generator = manifest.get("generator")
    source = manifest.get("source")
    if not isinstance(generator, dict) or generator.get("version") != GENERATOR_VERSION:
        raise CueAuditionError(f"generator version mismatch in {manifest_path}")
    if (
        not isinstance(source, dict)
        or source.get("external_audio_samples_incorporated") is not False
    ):
        raise CueAuditionError(f"source declaration mismatch in {manifest_path}")
    expected_manifest = _manifest(rendered)
    for family in rendered:
        try:
            actual_family = manifest["families"][family]
        except (KeyError, TypeError) as error:
            raise CueAuditionError(f"family {family} missing from {manifest_path}") from error
        if actual_family != expected_manifest["families"][family]:
            raise CueAuditionError(f"manifest metrics mismatch for family {family}")


def verify_packaged(families: Sequence[str]) -> None:
    """Prove that checked-in generated packs equal a fresh in-memory render."""

    rendered = _render_families(families)
    for family, cues in rendered.items():
        for cue, expected in cues.items():
            path = PACKAGED_SOUND_DIRECTORY / family / f"{cue}.wav"
            try:
                actual = path.read_bytes()
            except OSError as error:
                raise CueAuditionError(f"cannot read packaged cue {path}: {error}") from error
            if actual != expected:
                raise CueAuditionError(f"packaged cue differs from generator: {path}")


def _detect_player() -> str:
    for player in ("canberra-gtk-play", "pw-play", "paplay"):
        if shutil.which(player):
            return player
    raise CueAuditionError("no supported cue player found (canberra-gtk-play, pw-play, paplay)")


def _play_command(player: str, path: Path, volume: float) -> list[str]:
    if player == "canberra-gtk-play":
        decibels = 20.0 * math.log10(volume) if volume > 0.0 else -200.0
        return [
            player,
            f"--file={path}",
            "--description=Stenographer cue audition",
            "--cache-control=volatile",
            f"--volume={decibels:.2f}",
        ]
    if player == "pw-play":
        return [player, f"--volume={volume:.2f}", str(path)]
    return [player, f"--volume={int(volume * 65536)}", str(path)]


def _play_path(player: str, path: Path, volume: float) -> None:
    try:
        result = subprocess.run(
            _play_command(player, path, volume),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise CueAuditionError(f"could not start {player}: {error}") from error
    if result.returncode != 0:
        raise CueAuditionError(f"{player} failed while playing {path}")


def audition(output_directory: Path, families: Sequence[str], volume: float) -> None:
    """Play the bundled baseline, then selected candidates in lifecycle order."""

    selected = _normalize_families(families)
    baseline = PACKAGED_SOUND_DIRECTORY / "legacy"
    sets = (
        ("bundled baseline", baseline),
        *((family, output_directory / family) for family in selected),
    )
    for _label, directory in sets:
        for cue in CUE_ORDER:
            path = directory / f"{cue}.wav"
            if not path.is_file():
                raise CueAuditionError(f"cue not found: {path}; generate candidates first")

    player = _detect_player()
    print(f"Auditioning at volume {volume:.2f} with {player}; pauses are intentionally silent.")
    for set_index, (label, directory) in enumerate(sets, start=1):
        if set_index > 1:
            time.sleep(_FAMILY_PAUSE_SECONDS)
        print(f"\n{set_index}/{len(sets)}  {label}", flush=True)
        for cue_index, cue in enumerate(CUE_ORDER, start=1):
            note = (
                " (the current baseline is silent)"
                if label == "bundled baseline" and cue == "delivered"
                else ""
            )
            print(f"  {cue_index}/{len(CUE_ORDER)}  {cue}{note}", flush=True)
            _play_path(player, directory / f"{cue}.wav", volume)
            time.sleep(_CUE_PAUSE_SECONDS)


def _volume(value: str) -> float:
    try:
        volume = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("volume must be a number from 0 through 1") from error
    if not 0.0 <= volume <= 1.0:
        raise argparse.ArgumentTypeError("volume must be from 0 through 1")
    return volume


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"generated-file root (default: {DEFAULT_OUTPUT_DIRECTORY})",
    )
    parser.add_argument(
        "--family",
        choices=("all", *FAMILY_ORDER),
        default="all",
        help="candidate family to operate on (default: all)",
    )
    parser.add_argument(
        "--volume",
        type=_volume,
        default=DEFAULT_VOLUME,
        help=f"linear audition volume (default: {DEFAULT_VOLUME})",
    )
    parser.add_argument("--generate", action="store_true", help="render WAVs and manifest")
    parser.add_argument("--play", action="store_true", help="play baseline then candidates")
    parser.add_argument(
        "--verify-bytes",
        action="store_true",
        help="re-render and compare generated WAVs byte for byte",
    )
    parser.add_argument(
        "--verify-packaged",
        action="store_true",
        help="compare checked-in generated packs with a fresh render",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not (args.generate or args.play or args.verify_bytes or args.verify_packaged):
        parser.error(
            "select at least one action: --generate, --play, --verify-bytes, or --verify-packaged"
        )
    families = FAMILY_ORDER if args.family == "all" else (args.family,)
    try:
        if args.generate:
            manifest_path = generate_output(args.output_directory, families)
            print(f"Generated {len(families) * len(CUE_ORDER)} cues: {manifest_path}")
        if args.verify_bytes:
            verify_output(args.output_directory, families)
            print(f"Byte verification passed for {len(families) * len(CUE_ORDER)} cues.")
        if args.verify_packaged:
            verify_packaged(families)
            print(f"Packaged byte verification passed for {len(families) * len(CUE_ORDER)} cues.")
        if args.play:
            audition(args.output_directory, families, args.volume)
    except CueAuditionError as error:
        parser.exit(1, f"cue audition failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
