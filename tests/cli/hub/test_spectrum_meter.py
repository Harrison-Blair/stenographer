# SPDX-License-Identifier: GPL-3.0-or-later
"""Spectrum meter model and widget tests with synthetic tones and a fake clock."""

from __future__ import annotations

import asyncio
import threading

import numpy as np
from textual.app import App

from stenographer.cli.hub.widgets.spectrum_meter import SpectrumMeter
from stenographer.cli.hub.widgets.spectrum_meter_model import SpectrumMeterModel
from stenographer.cli.shared.no_background_css import NO_BACKGROUND_CSS
from tests.cli.hub.test_no_background import _painted_backgrounds

RATE = 16000
SCALE = "100  200  400  800 1k6 3k2 6k4"
DOTS = " ".join("·" * 18)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _tone(frequency, amplitude, seconds=0.1):
    t = np.arange(round(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def _heights(rows):
    assert len(rows) == 8
    return [sum(row[2 * band] == "█" for row in rows) for band in range(18)]


def _on_model(source="mic", **kwargs):
    model = SpectrumMeterModel(source, "Default input", **kwargs)
    model.set_state("on")
    return model


def test_a_200_hz_tone_lifts_the_low_bands_only():
    model = _on_model(floor_dbfs=-45.0)
    model.feed(_tone(200, 0.05))

    heights = _heights(model.rows)
    assert max(heights) > 0
    assert heights.index(max(heights)) == 3
    assert heights[14] == 0


def test_a_3_khz_tone_lifts_the_high_bands_only():
    model = _on_model(floor_dbfs=-45.0)
    model.feed(_tone(3000, 0.05))

    heights = _heights(model.rows)
    assert max(heights) > 0
    assert heights.index(max(heights)) == 14
    assert heights[3] == 0


def test_silence_draws_no_bar():
    model = _on_model()
    model.feed(np.zeros(1600, dtype=np.float32))

    assert _heights(model.rows) == [0] * 18
    assert all(set(row) <= {" "} for row in model.rows)


def test_the_floor_sets_which_levels_draw_a_bar():
    quiet = _tone(200, 0.003)
    high_floor = _on_model(floor_dbfs=-13.0)
    low_floor = _on_model(floor_dbfs=-96.0)
    high_floor.feed(quiet)
    low_floor.feed(quiet)

    assert max(_heights(high_floor.rows)) == 0
    assert max(_heights(low_floor.rows)) > 0


def test_on_state_head_scale_and_level_rows():
    model = _on_model()
    model.feed(_tone(200, 0.1))

    assert model.head == ("[m] MIC on · Default input", "○ quiet")
    model.speech = True
    assert model.head == ("[m] MIC on · Default input", "● speech")
    assert model.scale == SCALE
    # A 0.1 sine has RMS 0.0707, which is -23.01 dBFS.
    assert model.level_text == "-23 dBFS  peak -23"
    assert SpectrumMeterModel("system", "Default output").head[0].startswith("[s] SYSTEM")


def test_peak_holds_for_three_seconds_then_falls():
    clock = FakeClock()
    model = _on_model(clock=clock)
    model.feed(_tone(200, 0.5))  # RMS 0.354: -9.03 dBFS
    clock.now = 1.0
    model.feed(_tone(200, 0.01))  # RMS 0.00707: -43.01 dBFS
    assert model.level_text == "-43 dBFS  peak -9"

    clock.now = 2.9
    model.feed(_tone(200, 0.01))
    assert model.level_text == "-43 dBFS  peak -9"

    clock.now = 3.5
    model.feed(_tone(200, 0.01))
    assert model.level_text == "-43 dBFS  peak -43"


def test_idle_state_draws_a_dotted_grid_and_the_caller_text():
    model = SpectrumMeterModel("mic", "Default input")
    model.set_state("idle", idle_text="not recording")

    assert model.head[0] == "[m] MIC idle · Default input"
    assert model.rows == (DOTS,) * 8
    assert model.scale == SCALE
    assert model.level_text == "not recording"


def test_off_state_names_the_key_that_enables_the_source():
    mic = _on_model()
    mic.feed(_tone(200, 0.3))
    mic.set_state("off")
    system = SpectrumMeterModel("system", "Default output")
    system.set_state("off")

    assert mic.head[0] == "[m] MIC off · Default input"
    assert mic.level_text == "off · press m to enable"
    assert system.level_text == "off · press s to enable"
    assert _heights(mic.rows) == [0] * 18
    assert mic.scale == SCALE


def test_turning_on_again_starts_from_an_empty_meter():
    model = _on_model()
    model.feed(_tone(200, 0.5))
    model.set_state("idle", idle_text="not recording")
    model.set_state("on")

    assert _heights(model.rows) == [0] * 18
    assert model.level_text == "-inf dBFS  peak -inf"


class MeterApp(App):
    CSS = NO_BACKGROUND_CSS

    def __init__(self, meter):
        super().__init__(ansi_color=True)
        self.meter = meter

    def compose(self):
        yield self.meter


def _screen_text(app):
    return "\n".join(
        "".join(segment.text for segment in strip._segments)
        for strip in app.screen._compositor.render_strips()
    )


def test_widget_draws_blocks_fed_from_another_thread():
    meter = SpectrumMeter("mic", "Default input", floor_dbfs=-45.0)
    app = MeterApp(meter)

    async def exercise():
        async with app.run_test(size=(60, 16)) as pilot:
            meter.set_state("idle", idle_text="not recording")
            await pilot.pause()
            text = _screen_text(app)
            assert "MIC idle · Default input" in text
            assert "not recording" in text
            assert "█" not in text

            meter.set_state("on")
            meter.set_speech(True)
            feeder = threading.Thread(target=meter.feed, args=(_tone(200, 0.1),))
            feeder.start()
            feeder.join()
            await pilot.pause(0.2)
            text = _screen_text(app)
            assert "[m] MIC on · Default input" in text
            assert "● speech" in text
            assert "█" in text
            assert SCALE in text
            assert "-23 dBFS  peak -23" in text

            meter.set_state("off")
            await pilot.pause()
            text = _screen_text(app)
            assert "off · press m to enable" in text
            assert "█" not in text
            errors = []
            _painted_backgrounds(app, "meter off", errors)
            assert not errors

    asyncio.run(exercise())
