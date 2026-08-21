# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure tests for the optional recording spectrum analyzer."""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np

from stenographer.overlay.spectrum import (
    ATTACK_SECONDS,
    DEFAULT_SPECTRUM_FLOOR_DBFS,
    DISPLAY_GAMMA,
    FFT_MIN_SIZE,
    RELEASE_SECONDS,
    SPECTRUM_CEILING_DBFS,
    SPECTRUM_FPS,
    WINDOW_SECONDS,
    SpectrumAnalyzer,
    _band_analysis,
    analyze_spectrum,
    display_levels,
    fft_size_for_window,
    logarithmic_band_edges,
    quantize_spectrum,
    smooth_spectrum,
)
from stenographer.status import SPECTRUM_BANDS

_RATE = 16000
_FRAME_SECONDS = 1.0 / SPECTRUM_FPS


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
        levels = analyze_spectrum(_tone(frequency, amplitude=0.02), _RATE)
        assert int(np.argmax(levels)) == expected


def test_zero_padding_populates_the_lowest_narrow_band() -> None:
    window_size = round(_RATE * WINDOW_SECONDS)
    assert window_size == 512
    assert fft_size_for_window(window_size) == FFT_MIN_SIZE == 4096

    levels = analyze_spectrum(_tone(90.0, amplitude=0.02), _RATE)
    assert levels[0] > 0
    assert int(np.argmax(levels)) == 0


def test_band_range_clamps_to_device_nyquist_and_eight_kilohertz() -> None:
    assert logarithmic_band_edges(8000)[-1] == 4000.0
    assert logarithmic_band_edges(16000)[-1] == 8000.0
    assert logarithmic_band_edges(48000)[-1] == 8000.0


def test_fixed_mapping_is_exact_at_floor_and_ceiling() -> None:
    floor = DEFAULT_SPECTRUM_FLOOR_DBFS
    midpoint = (floor + SPECTRUM_CEILING_DBFS) / 2.0
    dbfs = np.array([floor - 20.0, floor, midpoint, SPECTRUM_CEILING_DBFS, 0.0, *([floor] * 13)])

    levels = display_levels(dbfs, floor)

    assert floor == -45.0
    assert SPECTRUM_CEILING_DBFS == -12.0
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


def test_display_response_is_monotonic_with_input_loudness() -> None:
    dominant_levels = [
        float(np.max(analyze_spectrum(_tone(1000.0, amplitude), _RATE)))
        for amplitude in (0.003, 0.01, 0.04)
    ]
    assert dominant_levels[0] < dominant_levels[1] < dominant_levels[2]


def test_digital_silence_and_nonfinite_samples_produce_zero_levels() -> None:
    assert np.array_equal(analyze_spectrum(np.zeros(512), _RATE), np.zeros(SPECTRUM_BANDS))
    invalid = np.full(512, np.nan)
    invalid[0] = np.inf
    invalid[1] = -np.inf
    assert np.array_equal(analyze_spectrum(invalid, _RATE), np.zeros(SPECTRUM_BANDS))
    assert np.array_equal(analyze_spectrum("not samples", _RATE), np.zeros(SPECTRUM_BANDS))


def test_first_frame_voice_response_is_immediate() -> None:
    analyzer = SpectrumAnalyzer(DEFAULT_SPECTRUM_FLOOR_DBFS)
    signal = _tone(1000.0, 0.01)
    first = analyzer.update(signal, _RATE, stream_epoch=1)
    unsmoothed = quantize_spectrum(analyze_spectrum(signal, _RATE))

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
