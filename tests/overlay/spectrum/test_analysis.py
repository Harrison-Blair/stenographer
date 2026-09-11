# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the optional recording spectrum analyzer."""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest

from stenographer.lib.contracts.constants import SPECTRUM_BANDS
from stenographer.overlay.spectrum.analysis import (
    ATTACK_SECONDS,
    DEFAULT_SPECTRUM_FLOOR_DBFS,
    DISPLAY_GAMMA,
    DISPLAY_RANGE_DBFS,
    FFT_MIN_SIZE,
    MAX_SPECTRUM_FLOOR_DBFS,
    MIN_SPECTRUM_FLOOR_DBFS,
    RELEASE_SECONDS,
    SPECTRUM_CEILING_DBFS,
    SPECTRUM_FPS,
    WINDOW_SECONDS,
    _band_analysis,
    _band_dbfs,
    display_levels,
    fft_size_for_window,
    logarithmic_band_edges,
    quantize_spectrum,
    smooth_spectrum,
)
from stenographer.overlay.spectrum.spectrum_analyzer import SpectrumAnalyzer

_RATE = 16000
_FRAME_SECONDS = 1.0 / SPECTRUM_FPS


def _levels(samples: object) -> np.ndarray:
    """The analyzer's own unsmoothed path: band dBFS mapped onto display levels."""
    return display_levels(_band_dbfs(samples, _RATE))


def _tone(
    frequency: float,
    amplitude: float = 0.1,
    *,
    sample_rate: int = _RATE,
) -> np.ndarray:
    times = np.arange(round(sample_rate * WINDOW_SECONDS), dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * times)).astype(np.float32)


def test_exactly_eighteen_logarithmic_bands_place_tones_by_frequency() -> None:
    edges = logarithmic_band_edges(_RATE)
    assert SPECTRUM_BANDS == 18
    assert edges.size == SPECTRUM_BANDS + 1

    for expected in range(SPECTRUM_BANDS):
        frequency = math.sqrt(edges[expected] * edges[expected + 1])
        levels = _levels(_tone(frequency, amplitude=0.02))
        assert int(np.argmax(levels)) == expected


def test_zero_padding_populates_the_lowest_narrow_band() -> None:
    window_size = round(_RATE * WINDOW_SECONDS)
    assert window_size == 512
    assert fft_size_for_window(window_size) == FFT_MIN_SIZE == 4096

    levels = _levels(_tone(90.0, amplitude=0.02))
    assert levels[0] > 0
    assert int(np.argmax(levels)) == 0


def test_band_range_clamps_to_device_nyquist_and_eight_kilohertz() -> None:
    assert logarithmic_band_edges(8000)[-1] == 4000.0
    assert logarithmic_band_edges(16000)[-1] == 8000.0
    assert logarithmic_band_edges(48000)[-1] == 8000.0


def test_fixed_mapping_is_exact_at_floor_and_ceiling() -> None:
    floor = DEFAULT_SPECTRUM_FLOOR_DBFS
    ceiling = min(SPECTRUM_CEILING_DBFS, floor + DISPLAY_RANGE_DBFS)
    midpoint = (floor + ceiling) / 2.0
    dbfs = np.array([floor - 20.0, floor, midpoint, ceiling, 0.0, *([floor] * 13)])

    levels = display_levels(dbfs, floor)

    assert floor == -45.0
    assert SPECTRUM_CEILING_DBFS == -12.0
    assert DISPLAY_RANGE_DBFS == 30.0
    assert levels[0] == levels[1] == 0.0
    assert levels[2] == 0.5**DISPLAY_GAMMA
    assert levels[3] == levels[4] == 1.0
    assert np.array_equal(levels[5:], np.zeros(13))


def test_measured_background_range_maps_to_zero() -> None:
    background_dbfs = np.array(
        [
            -68.2,
            -63.4,
            -60.1,
            -58.7,
            -57.9,
            -56.2,
            -54.8,
            -53.6,
            -52.9,
            -51.4,
            -50.8,
            -49.7,
            -48.6,
            -47.9,
            -46.8,
            -46.1,
            -45.4,
            -45.0,
        ]
    )

    assert np.array_equal(
        display_levels(background_dbfs, DEFAULT_SPECTRUM_FLOOR_DBFS),
        np.zeros(SPECTRUM_BANDS),
    )


def test_less_negative_floor_suppresses_more_input() -> None:
    signal = np.full(SPECTRUM_BANDS, -42.0)

    assert max(display_levels(signal, -45.0)) > 0
    assert np.array_equal(display_levels(signal, -40.0), np.zeros(SPECTRUM_BANDS))


def test_per_band_floors_isolate_loud_background_from_quiet_voice_bands() -> None:
    dbfs = np.full(SPECTRUM_BANDS, -58.0)
    floors = np.full(SPECTRUM_BANDS, -65.0)
    floors[0] = -35.0
    dbfs[0] = -36.0

    levels = display_levels(dbfs, floors)

    assert levels[0] == 0.0
    assert np.all(levels[1:] > 0.0)


def test_per_band_mapping_uses_a_fixed_thirty_db_visual_range() -> None:
    floors = np.linspace(-90.0, -45.0, SPECTRUM_BANDS)
    dbfs = floors + 15.0

    levels = display_levels(dbfs, floors)

    assert np.allclose(levels, 0.5**DISPLAY_GAMMA)


def test_display_response_is_monotonic_with_input_loudness() -> None:
    dominant_levels = [
        float(np.max(_levels(_tone(1000.0, amplitude)))) for amplitude in (0.003, 0.01, 0.04)
    ]
    assert dominant_levels[0] < dominant_levels[1] < dominant_levels[2]


def test_digital_silence_and_nonfinite_samples_produce_zero_levels() -> None:
    assert np.array_equal(_levels(np.zeros(512)), np.zeros(SPECTRUM_BANDS))
    invalid = np.full(512, np.nan)
    invalid[0] = np.inf
    invalid[1] = -np.inf
    assert np.array_equal(_levels(invalid), np.zeros(SPECTRUM_BANDS))
    assert np.array_equal(_levels("not samples"), np.zeros(SPECTRUM_BANDS))


def test_first_frame_voice_response_is_immediate() -> None:
    analyzer = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    signal = _tone(1000.0, 0.01)
    first = analyzer.update(signal, _RATE, stream_epoch=1)
    unsmoothed = quantize_spectrum(_levels(signal))

    assert max(first) > 0
    assert max(abs(actual - target) for actual, target in zip(first, unsmoothed, strict=True)) <= 1


def test_release_reaches_near_baseline_within_seven_frames() -> None:
    analyzer = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    tone = _tone(1000.0, 0.01)
    analyzer.update(tone, _RATE, stream_epoch=1)

    for _ in range(7):
        released = analyzer.update(np.zeros(tone.size), _RATE, stream_epoch=1)

    assert max(released) <= 3


def test_attack_and_release_use_their_documented_time_constants() -> None:
    assert SPECTRUM_FPS == 60
    assert ATTACK_SECONDS == 0.0025
    assert RELEASE_SECONDS == 0.0225

    zeros = np.zeros(SPECTRUM_BANDS)
    ones = np.ones(SPECTRUM_BANDS)

    attacked = smooth_spectrum(zeros, ones, _FRAME_SECONDS)
    released = smooth_spectrum(ones, zeros, _FRAME_SECONDS)

    assert np.allclose(attacked, 1.0 - math.exp(-_FRAME_SECONDS / ATTACK_SECONDS))
    assert np.allclose(released, math.exp(-_FRAME_SECONDS / RELEASE_SECONDS))
    assert np.all(attacked > released)


def test_output_does_not_depend_on_prior_recordings() -> None:
    after_history = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    for _ in range(SPECTRUM_FPS * 3):
        after_history.update(_tone(1000.0, 0.5), _RATE, stream_epoch=7)
    after_history.begin_recording()

    fresh = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    signal = _tone(440.0, 0.01)

    assert after_history.update(signal, _RATE, stream_epoch=7) == fresh.update(
        signal, _RATE, stream_epoch=7
    )


def test_configured_floor_controls_analyzer_mapping() -> None:
    signal = _tone(1000.0, 0.008)
    sensitive = SpectrumAnalyzer(-50.0).update(signal, _RATE, stream_epoch=1)
    suppressed = SpectrumAnalyzer(-30.0).update(signal, _RATE, stream_epoch=1)

    assert max(sensitive) > 0
    assert max(suppressed) == 0


def test_sustained_signal_never_becomes_the_display_baseline() -> None:
    floors = tuple([-70.0] * SPECTRUM_BANDS)
    analyzer = SpectrumAnalyzer(floors)
    signal = _tone(1000.0, 0.002)

    first = analyzer.update(signal, _RATE, stream_epoch=1)
    for _ in range(SPECTRUM_FPS * 120):
        last = analyzer.update(signal, _RATE, stream_epoch=1)

    assert max(first) > 0
    assert last == first


def test_reused_analyzer_matches_fresh_analyzer_after_reconfiguration() -> None:
    reused = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    for _ in range(5):
        reused.update(_tone(2000.0, 0.3, sample_rate=48000), 48000, stream_epoch=3)

    blocks = [
        _tone(300.0, 0.02),
        _tone(1000.0, 0.01),
        np.zeros(128, dtype=np.float32),
        _tone(4000.0, 0.05),
    ]
    fresh = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    for block in blocks:
        assert reused.update(block, _RATE, stream_epoch=4) == fresh.update(
            block, _RATE, stream_epoch=4
        )

    # A stream-epoch change alone still reconfigures (clears retained state).
    assert reused.update(blocks[0], _RATE, stream_epoch=5) == SpectrumAnalyzer(
        DEFAULT_SPECTRUM_FLOOR_DBFS
    ).update(blocks[0], _RATE, stream_epoch=5)

    # A sample-rate change alone still reconfigures.
    tone_8k = _tone(1000.0, 0.02, sample_rate=8000)
    assert reused.update(tone_8k, 8000, stream_epoch=5) == SpectrumAnalyzer(
        DEFAULT_SPECTRUM_FLOOR_DBFS
    ).update(tone_8k, 8000, stream_epoch=5)


def test_cached_band_ranges_match_boolean_mask_oracle() -> None:
    for sample_rate in (100, 8000, 16000, 44100, 48000, 192000):
        for window_size in (2, 3, 512, 1024):
            analysis = _band_analysis(sample_rate, window_size)
            assert np.array_equal(analysis.window, np.hanning(window_size))
            assert analysis.coherent_gain == float(np.sum(np.hanning(window_size)))
            assert analysis.fft_size == fft_size_for_window(window_size)

            frequencies = np.fft.rfftfreq(analysis.fft_size, d=1.0 / sample_rate)
            edges = logarithmic_band_edges(sample_rate)
            assert len(analysis.bands) == SPECTRUM_BANDS
            for index, (lower, upper) in enumerate(pairwise(edges)):
                key = (sample_rate, window_size, index)
                if upper <= lower:
                    expected = np.zeros(frequencies.size, dtype=bool)
                elif index == SPECTRUM_BANDS - 1:
                    expected = (frequencies >= lower) & (frequencies <= upper)
                else:
                    expected = (frequencies >= lower) & (frequencies < upper)
                band = analysis.bands[index]
                assert (band is None) == (not expected.any()), key
                selected = np.zeros(frequencies.size, dtype=bool)
                if band is not None:
                    selected[band[0] : band[1]] = True
                assert np.array_equal(selected, expected), key

    # The sweep genuinely exercises both None paths.
    assert _band_analysis(100, 512).bands == (None,) * SPECTRUM_BANDS  # degenerate edges
    assert any(band is None for band in _band_analysis(192000, 512).bands)  # empty mask


def test_partial_block_shift_matches_roll_oracle_in_place() -> None:
    rng = np.random.default_rng(7)
    analyzer = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    window_size = round(_RATE * WINDOW_SECONDS)
    fill = rng.uniform(-0.1, 0.1, window_size).astype(np.float32)
    analyzer.update(fill, _RATE, stream_epoch=1)
    retained = analyzer._window
    assert np.array_equal(retained, fill)

    block = rng.uniform(-0.1, 0.1, 100).astype(np.float32)
    expected = np.roll(fill, -block.size)
    expected[-block.size :] = block
    analyzer.update(block, _RATE, stream_epoch=1)

    assert analyzer._window is retained  # begin_recording() relies on buffer identity
    assert np.array_equal(analyzer._window, expected)


def test_quantization_is_clamped_deterministic_and_exactly_eighteen_levels() -> None:
    values = np.array([-1.0, 0.0, 0.5, 1.0, 2.0, np.nan, np.inf, -np.inf, *([0.0] * 10)])

    quantized = quantize_spectrum(values)

    assert len(quantized) == SPECTRUM_BANDS
    assert quantized == (0, 0, 128, 255, 255, 0, 255, 0, *([0] * 10))


@pytest.mark.parametrize(
    "floor",
    [
        MIN_SPECTRUM_FLOOR_DBFS - 0.1,
        MAX_SPECTRUM_FLOOR_DBFS + 0.1,
        float("inf"),
        float("nan"),
    ],
)
def test_a_scalar_floor_outside_the_usable_range_is_refused(floor: float) -> None:
    """A floor above the ceiling would invert the display mapping, and one
    below -96 dBFS would map dither noise to full-height bars.
    """
    with pytest.raises(ValueError, match="spectrum floor must be in"):
        display_levels(np.full(SPECTRUM_BANDS, -30.0), floor)


@pytest.mark.parametrize("floor", [object(), "quiet", {"band": 1}])
def test_a_floor_that_is_neither_a_number_nor_a_profile_is_refused(floor: object) -> None:
    with pytest.raises(TypeError, match="number or 18-band sequence"):
        display_levels(np.full(SPECTRUM_BANDS, -30.0), floor)


@pytest.mark.parametrize("size", [SPECTRUM_BANDS - 1, SPECTRUM_BANDS + 1, 0])
def test_a_calibrated_profile_must_name_every_band(size: int) -> None:
    with pytest.raises(ValueError, match=f"requires {SPECTRUM_BANDS} bands"):
        display_levels(np.full(SPECTRUM_BANDS, -30.0), np.full(size, -45.0))


@pytest.mark.parametrize("bad", [-200.0, 0.0, float("nan")])
def test_one_unusable_band_invalidates_a_whole_profile(bad: float) -> None:
    profile = np.full(SPECTRUM_BANDS, -45.0)
    profile[3] = bad

    with pytest.raises(ValueError, match="spectrum floor must be in"):
        display_levels(np.full(SPECTRUM_BANDS, -30.0), profile)


@pytest.mark.parametrize("sample_rate", [0, -1, True, 16000.0])
def test_band_measurement_requires_a_negotiated_positive_sample_rate(
    sample_rate: object,
) -> None:
    with pytest.raises(ValueError, match="sample rate must be a positive integer"):
        _band_dbfs(np.zeros(64, dtype=np.float32), sample_rate)


@pytest.mark.parametrize("sample_count", [0, -1, True, 4096.0])
def test_the_fft_size_requires_a_positive_whole_window(sample_count: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        fft_size_for_window(sample_count)


@pytest.mark.parametrize("samples", [np.zeros(1), np.zeros(0), object(), "audio"])
def test_a_block_too_small_or_too_odd_to_measure_reads_as_silence(samples: object) -> None:
    """Callback edges hand the analyzer stubs; they must read as silence rather
    than raise inside the recording loop.
    """
    assert np.all(np.isneginf(_band_dbfs(samples, _RATE)))


def test_a_window_with_no_analysis_gain_reads_as_silence() -> None:
    """``np.hanning(2)`` is two zeros: the shortest measurable block has no
    coherent gain to normalize by, so no band can claim a level.
    """
    assert np.all(np.isneginf(_band_dbfs(np.array([0.5, -0.5]), _RATE)))


def test_a_sample_rate_below_the_band_range_leaves_every_band_empty() -> None:
    """At 120 Hz the whole 80 Hz - 8 kHz range sits above Nyquist, so every
    band collapses to an empty bin range and reads as silence, not an error.
    """
    measured = _band_dbfs(np.linspace(-0.5, 0.5, 64), 120)

    assert measured.shape == (SPECTRUM_BANDS,)
    assert np.all(np.isneginf(measured))


@pytest.mark.parametrize("size", [SPECTRUM_BANDS - 1, SPECTRUM_BANDS + 1])
def test_display_mapping_requires_exactly_eighteen_measurements(size: int) -> None:
    with pytest.raises(ValueError, match=f"requires {SPECTRUM_BANDS} levels"):
        display_levels(np.full(size, -30.0))


@pytest.mark.parametrize(
    ("previous", "target"),
    [
        (np.zeros(SPECTRUM_BANDS - 1), np.zeros(SPECTRUM_BANDS)),
        (np.zeros(SPECTRUM_BANDS), np.zeros(SPECTRUM_BANDS + 1)),
    ],
)
def test_smoothing_requires_both_frames_to_cover_every_band(previous, target) -> None:
    with pytest.raises(ValueError, match=f"requires {SPECTRUM_BANDS} levels"):
        smooth_spectrum(previous, target, _FRAME_SECONDS)


@pytest.mark.parametrize("elapsed", [-0.001, float("nan"), float("inf")])
def test_smoothing_refuses_an_elapsed_time_that_is_not_a_real_interval(
    elapsed: float,
) -> None:
    frame = np.zeros(SPECTRUM_BANDS)

    with pytest.raises(ValueError, match="finite and non-negative"):
        smooth_spectrum(frame, frame, elapsed)


@pytest.mark.parametrize(
    ("attack", "release"),
    [(0.0, RELEASE_SECONDS), (ATTACK_SECONDS, 0.0), (-1.0, RELEASE_SECONDS)],
)
def test_smoothing_refuses_time_constants_that_would_divide_by_zero(
    attack: float, release: float
) -> None:
    frame = np.zeros(SPECTRUM_BANDS)

    with pytest.raises(ValueError, match="finite and positive"):
        smooth_spectrum(frame, frame, _FRAME_SECONDS, attack=attack, release=release)


@pytest.mark.parametrize("size", [SPECTRUM_BANDS - 1, SPECTRUM_BANDS + 1])
def test_quantization_requires_exactly_eighteen_levels(size: int) -> None:
    with pytest.raises(ValueError, match=f"requires {SPECTRUM_BANDS} levels"):
        quantize_spectrum(np.zeros(size))


def test_the_analyzer_reports_the_fixed_floor_it_was_configured_with() -> None:
    scalar = SpectrumAnalyzer(-40.0)
    profile = SpectrumAnalyzer(tuple(float(-50 - index) for index in range(SPECTRUM_BANDS)))

    assert scalar.floor_dbfs == -40.0
    assert profile.floor_dbfs == tuple(float(-50 - index) for index in range(SPECTRUM_BANDS))


def test_an_analyzer_cannot_be_built_on_an_unusable_floor() -> None:
    with pytest.raises(ValueError, match="spectrum floor must be in"):
        SpectrumAnalyzer(0.0)


@pytest.mark.parametrize("stream_epoch", [-1, True, 0.0, "0"])
def test_the_analyzer_requires_a_real_stream_epoch(stream_epoch: object) -> None:
    """The epoch is what tells one device stream from the next; a bool would
    fold two of them together and carry stale samples across.
    """
    analyzer = SpectrumAnalyzer()

    with pytest.raises(ValueError, match="stream epoch must be a non-negative integer"):
        analyzer.update(_tone(1000.0), _RATE, stream_epoch=stream_epoch)


@pytest.mark.parametrize("samples", [object(), "audio", {"left": 1}])
def test_an_unreadable_block_leaves_the_window_and_frame_intact(samples: object) -> None:
    analyzer = SpectrumAnalyzer()
    expected = analyzer.update(np.zeros(512, dtype=np.float32), _RATE, stream_epoch=0)

    assert analyzer.update(samples, _RATE, stream_epoch=0) == expected


def test_resetting_forgets_the_stream_so_the_next_block_reconfigures() -> None:
    """A reset analyzer must not carry the previous device's samples into the
    first frame of the next recording.
    """
    analyzer = SpectrumAnalyzer()
    loud = analyzer.update(_tone(1000.0, 0.5), _RATE, stream_epoch=0)
    assert max(loud) > 0

    analyzer.reset()
    first = analyzer.update(np.zeros(0, dtype=np.float32), _RATE, stream_epoch=0)

    assert first == (0,) * SPECTRUM_BANDS


def test_beginning_a_recording_before_any_block_has_nothing_to_clear() -> None:
    analyzer = SpectrumAnalyzer()

    analyzer.begin_recording()

    assert analyzer.update(np.zeros(0, dtype=np.float32), _RATE, stream_epoch=0) == (
        (0,) * SPECTRUM_BANDS
    )
