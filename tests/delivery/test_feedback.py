# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure filesystem-policy tests for sound-pack discovery and resolution."""

from __future__ import annotations

import logging
import pathlib
import wave

import pytest

from stenographer.config import FeedbackConfig
from stenographer.delivery.feedback import (
    BUNDLED_PACKS,
    CUE_ORDER,
    DEFAULT_SOUND_PACK,
    Feedback,
    _wav_header_ok,
    _wav_payload_ok,
    cue_audible,
    discover_sound_packs,
    effective_sound_pack_name,
    is_valid_pack_name,
    load_sound_pack,
    preview_volume,
    resolve_sound_pack,
    sound_pack_cue_paths,
)

_BUNDLED = (
    pathlib.Path(__file__).parent.parent.parent / "src" / "stenographer" / "assets" / "sounds"
)


def _write_wav(
    path: pathlib.Path,
    *,
    channels: int = 1,
    sample_width: int = 2,
    sample_rate: int = 48_000,
    frames: int = 480,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes([1]) * frames * channels * sample_width)


def _write_pack(root: pathlib.Path, **wav_options: int) -> pathlib.Path:
    for cue in CUE_ORDER:
        _write_wav(root / f"{cue}.wav", **wav_options)
    return root


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a", True),
        ("pack-01", True),
        ("a" * 64, True),
        ("", False),
        ("-pack", False),
        ("Pack", False),
        ("pack_name", False),
        ("a" * 65, False),
        ("pack\n", False),
    ],
)
def test_pack_name_slug(name, expected):
    assert is_valid_pack_name(name) is expected


def test_complete_pack_accepts_unrelated_extra_files(tmp_path):
    pack = _write_pack(tmp_path / "sounds" / "custom")
    (pack / "notes.txt").write_text("ignored", encoding="utf-8")

    paths = sound_pack_cue_paths(pack, containment_root=tmp_path / "sounds")

    assert paths is not None
    assert tuple(path.stem for path in paths) == CUE_ORDER
    assert sound_pack_cue_paths(pack, containment_root=tmp_path / "sounds") is not None


@pytest.mark.parametrize(
    "options",
    [
        {"channels": 3},
        {"sample_rate": 7_999},
        {"sample_rate": 192_001},
        {"frames": 0},
        {"sample_rate": 8_000, "frames": 2_400},
    ],
)
def test_pack_rejects_wavs_outside_supported_bounds(tmp_path, options):
    pack = _write_pack(tmp_path / "sounds" / "custom", **options)
    assert sound_pack_cue_paths(pack, containment_root=tmp_path / "sounds") is None


def test_pack_accepts_supported_pcm_width_channel_and_rate_edges(tmp_path):
    for index, (channels, width, rate) in enumerate(
        ((1, 1, 8_000), (2, 3, 48_000), (2, 4, 192_000))
    ):
        pack = _write_pack(
            tmp_path / "sounds" / f"custom-{index}",
            channels=channels,
            sample_width=width,
            sample_rate=rate,
        )
        assert sound_pack_cue_paths(pack, containment_root=tmp_path / "sounds") is not None


def test_pack_rejects_corrupt_truncated_and_incomplete_cues(tmp_path):
    incomplete = _write_pack(tmp_path / "sounds" / "incomplete")
    (incomplete / "error.wav").unlink()
    corrupt = _write_pack(tmp_path / "sounds" / "corrupt")
    (corrupt / "record_stop.wav").write_bytes(b"RIFF")
    truncated = _write_pack(tmp_path / "sounds" / "truncated")
    path = truncated / "delivered.wav"
    path.write_bytes(path.read_bytes()[:-1])
    unsupported_width = _write_pack(tmp_path / "sounds" / "unsupported-width")
    path = unsupported_width / "record_start.wav"
    data = bytearray(path.read_bytes())
    data[34:36] = (40).to_bytes(2, byteorder="little")
    path.write_bytes(data)

    assert sound_pack_cue_paths(incomplete, containment_root=tmp_path / "sounds") is None
    assert sound_pack_cue_paths(corrupt, containment_root=tmp_path / "sounds") is None
    assert sound_pack_cue_paths(truncated, containment_root=tmp_path / "sounds") is None
    assert sound_pack_cue_paths(unsupported_width, containment_root=tmp_path / "sounds") is None


def test_pack_rejects_symlink_that_escapes_pack(tmp_path):
    custom_root = tmp_path / "sounds"
    pack = _write_pack(custom_root / "custom")
    outside = tmp_path / "outside.wav"
    _write_wav(outside)
    (pack / "error.wav").unlink()
    try:
        (pack / "error.wav").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert sound_pack_cue_paths(pack, containment_root=custom_root) is None


def test_pack_directory_symlink_cannot_escape_custom_root(tmp_path):
    custom_root = tmp_path / "sounds"
    custom_root.mkdir()
    outside = _write_pack(tmp_path / "outside")
    try:
        (custom_root / "custom").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert discover_sound_packs(tmp_path, bundled_root=_BUNDLED) == BUNDLED_PACKS


def test_sounds_directory_symlink_cannot_escape_config_directory(tmp_path):
    outside = tmp_path / "outside"
    _write_pack(outside / "custom")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    try:
        (config_dir / "sounds").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert discover_sound_packs(config_dir, bundled_root=_BUNDLED) == BUNDLED_PACKS
    assert load_sound_pack("custom", config_dir, bundled_root=_BUNDLED) is None


def test_discovery_orders_bundled_then_sorted_valid_custom_packs(tmp_path):
    custom_root = tmp_path / "sounds"
    _write_pack(custom_root / "zebra")
    _write_pack(custom_root / "alpha")
    _write_pack(custom_root / "broken").joinpath("delivered.wav").unlink()
    _write_pack(custom_root / "Not-A-Slug")

    assert discover_sound_packs(tmp_path, bundled_root=_BUNDLED) == (
        *BUNDLED_PACKS,
        "alpha",
        "zebra",
    )


def test_bundled_names_win_custom_collisions(tmp_path):
    custom_legacy = _write_pack(tmp_path / "sounds" / "legacy", sample_rate=8_000)

    selected = load_sound_pack("legacy", tmp_path, bundled_root=_BUNDLED)

    assert selected is not None
    assert selected.bundled
    assert selected.root == _BUNDLED / "legacy"
    assert all(custom_legacy not in path.parents for path in selected.cue_paths if path is not None)
    assert discover_sound_packs(tmp_path, bundled_root=_BUNDLED).count("legacy") == 1


def test_missing_custom_falls_back_once_to_minimal_ui(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        selected = resolve_sound_pack("missing", tmp_path, bundled_root=_BUNDLED)

    assert selected.name == DEFAULT_SOUND_PACK
    assert selected.bundled
    assert selected.fallback
    assert selected.complete
    assert len(caplog.records) == 1


def test_missing_fallback_assets_disable_only_unavailable_cues(tmp_path, caplog):
    bundled = tmp_path / "bundled"
    fallback = _write_pack(bundled / DEFAULT_SOUND_PACK)
    (fallback / "error.wav").unlink()

    with caplog.at_level(logging.WARNING):
        selected = resolve_sound_pack("missing", tmp_path, bundled_root=bundled)

    assert selected.fallback
    assert selected.path_for("record_start") is not None
    assert selected.path_for("error") is None
    assert len(caplog.records) == 2


def test_preview_volume_is_audible_without_mutating_muted_settings():
    muted = FeedbackConfig(volume=0.25, mute=True)
    zero = FeedbackConfig(volume=0.0, mute=False)
    configured = FeedbackConfig(volume=0.25, mute=False)

    assert preview_volume(muted) == 0.6
    assert preview_volume(zero) == 0.6
    assert preview_volume(configured) == 0.25
    assert muted == FeedbackConfig(volume=0.25, mute=True)


def test_four_bundled_packs_each_have_exactly_four_valid_cues():
    assert {path.name for path in _BUNDLED.iterdir() if path.is_dir()} == set(BUNDLED_PACKS)
    for name in BUNDLED_PACKS:
        pack = _BUNDLED / name
        assert {path.name for path in pack.iterdir()} == {f"{cue}.wav" for cue in CUE_ORDER}
        assert sound_pack_cue_paths(pack, containment_root=_BUNDLED) is not None, name


@pytest.mark.parametrize(
    ("channels", "sample_width", "sample_rate", "frame_count", "compression", "expected"),
    [
        (1, 1, 8_000, 1, "NONE", True),
        (2, 4, 192_000, 57_599, "NONE", True),
        (2, 2, 48_000, 14_399, "NONE", True),
        (0, 2, 48_000, 480, "NONE", False),
        (3, 2, 48_000, 480, "NONE", False),
        (1, 5, 48_000, 480, "NONE", False),
        (1, 0, 48_000, 480, "NONE", False),
        (1, 2, 7_999, 480, "NONE", False),
        (1, 2, 192_001, 480, "NONE", False),
        (1, 2, 48_000, 0, "NONE", False),
        (1, 2, 48_000, 14_400, "NONE", False),
        (1, 2, 48_000, 2**62, "NONE", False),
        (1, 2, 48_000, 480, "ULAW", False),
    ],
)
def test_wav_header_predicate_bounds(
    channels, sample_width, sample_rate, frame_count, compression, expected
):
    assert _wav_header_ok(channels, sample_width, sample_rate, frame_count, compression) is expected


def test_discovery_omits_incomplete_bundled_packs_in_order(tmp_path):
    bundled = tmp_path / "bundled"
    for name in BUNDLED_PACKS:
        _write_pack(bundled / name)
    (bundled / BUNDLED_PACKS[1] / "record_stop.wav").unlink()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    assert discover_sound_packs(config_dir, bundled_root=bundled) == (
        BUNDLED_PACKS[0],
        *BUNDLED_PACKS[2:],
    )


def test_effective_name_uses_strict_custom_pack(tmp_path):
    _write_pack(tmp_path / "sounds" / "custom")

    assert effective_sound_pack_name("custom", tmp_path, bundled_root=_BUNDLED) == "custom"


def test_effective_name_reports_partial_bundled_default(tmp_path):
    bundled = tmp_path / "bundled"
    (_write_pack(bundled / DEFAULT_SOUND_PACK) / "error.wav").unlink()

    assert effective_sound_pack_name("missing", tmp_path, bundled_root=bundled) == (
        DEFAULT_SOUND_PACK
    )


def test_effective_name_is_none_when_nothing_resolves(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()

    assert effective_sound_pack_name("missing", tmp_path, bundled_root=bundled) is None


def test_feedback_requires_explicit_config_dir():
    with pytest.raises(TypeError):
        Feedback(cfg=FeedbackConfig(volume=0.6, mute=False), player=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("mute", "volume", "has_player", "expected"),
    [
        (False, 0.6, True, True),
        (True, 0.6, True, False),
        (False, 0.0, True, False),
        (False, -0.1, True, False),
        (False, 0.6, False, False),
    ],
)
def test_cue_audible_needs_unmuted_positive_volume_and_a_player(mute, volume, has_player, expected):
    assert cue_audible(mute, volume, has_player=has_player) is expected


def test_wav_payload_must_match_the_declared_frame_geometry():
    assert _wav_payload_ok(4800, 1200, 2, 2) is True
    assert _wav_payload_ok(4799, 1200, 2, 2) is False
    assert _wav_payload_ok(0, 0, 1, 2) is True
