# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Wayland spectrum visualizer."""

from __future__ import annotations

import sys
import threading

import numpy as np

from stenographer import visualizer
from stenographer.config import VisualizerConfig
from stenographer.visualizer import (
    LayerShellOverlay,
    SpectrumAnalyzer,
    _register_application_font,
    analyze_frequency_bands,
)


def test_analyze_frequency_bands_silence_is_empty() -> None:
    levels = analyze_frequency_bands(
        np.zeros(1024, dtype=np.float32),
        16000,
        16,
        80.0,
        8000.0,
    )
    assert levels.shape == (16,)
    assert np.array_equal(levels, np.zeros(16, dtype=np.float32))


def test_analyze_frequency_bands_places_tone_in_logarithmic_band() -> None:
    sample_rate = 16000
    frequency = 440.0
    time = np.arange(2048, dtype=np.float32) / sample_rate
    samples = 0.5 * np.sin(2 * np.pi * frequency * time)
    levels = analyze_frequency_bands(samples, sample_rate, 16, 80.0, 8000.0)
    edges = np.geomspace(80.0, 8000.0, 17)
    expected = int(np.searchsorted(edges, frequency, side="right") - 1)
    assert int(np.argmax(levels)) == expected
    assert levels[expected] > 0.8


def test_analyze_frequency_bands_clamps_to_nyquist() -> None:
    sample_rate = 8000
    time = np.arange(1024, dtype=np.float32) / sample_rate
    samples = np.sin(2 * np.pi * 1000 * time)
    levels = analyze_frequency_bands(samples, sample_rate, 12, 80.0, 8000.0)
    assert levels.shape == (12,)
    assert np.all(np.isfinite(levels))
    assert np.all((levels >= 0.0) & (levels <= 1.0))


def test_register_application_font_uses_active_pango_font_map() -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeFontMap:
        def add_font_file(self, path: str) -> bool:
            calls.append(("add", path))
            return True

        def changed(self) -> None:
            calls.append(("changed", None))

        def get_family(self, family: str) -> object | None:
            calls.append(("family", family))
            return object() if family == "Caveat" else None

    assert _register_application_font(FakeFontMap(), "/fonts/Caveat.ttf", "Caveat")
    assert calls == [
        ("add", "/fonts/Caveat.ttf"),
        ("changed", None),
        ("family", "Caveat"),
    ]


def test_spectrum_analyzer_delivers_levels_off_caller_thread() -> None:
    delivered = threading.Event()
    callback_threads: list[int] = []

    def collect(_levels: list[float]) -> None:
        callback_threads.append(threading.get_ident())
        delivered.set()

    analyzer = SpectrumAnalyzer(
        band_count=8,
        min_frequency=80.0,
        max_frequency=8000.0,
        on_levels=collect,
    )
    try:
        caller_thread = threading.get_ident()
        analyzer.set_active(True)
        analyzer.submit(np.ones(1024, dtype=np.float32), 16000)
        assert delivered.wait(timeout=1.0)
        assert callback_threads != [caller_thread]
    finally:
        analyzer.close()


def test_frozen_overlay_falls_back_to_system_layer_shell(
    monkeypatch,
    tmp_path,
) -> None:
    captured_environment: dict[str, str] = {}
    font_path = tmp_path / "Caveat-wght.ttf"
    font_path.touch()

    class FakeStream:
        def write(self, _value: str) -> None:
            pass

        def flush(self) -> None:
            pass

        def readline(self) -> str:
            return "READY\n"

    class FakeProcess:
        stdin = FakeStream()
        stdout = FakeStream()

        def poll(self) -> None:
            return None

    def fake_popen(_command, **kwargs):
        captured_environment.update(kwargs["env"])
        return FakeProcess()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(LayerShellOverlay, "probe", staticmethod(lambda: True))
    monkeypatch.setattr(
        visualizer.ctypes.util,
        "find_library",
        lambda name: "libgtk4-layer-shell.so.0" if name == "gtk4-layer-shell" else None,
    )
    monkeypatch.setattr(visualizer.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(visualizer.select, "select", lambda *_args: ([object()], [], []))

    overlay = LayerShellOverlay(
        VisualizerConfig(
            enabled=True,
            frequency_bands=16,
            min_frequency=80.0,
            max_frequency=8000.0,
            margin_bottom=32,
        ),
        font_path=font_path,
    )

    assert overlay.show_state("listening")
    assert captured_environment["LD_PRELOAD"].split(":")[0] == ("libgtk4-layer-shell.so.0")
    assert captured_environment["STENOGRAPHER_FONT_PATH"] == str(font_path)
