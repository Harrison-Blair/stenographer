# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Wayland spectrum visualizer."""

from __future__ import annotations

import json
import queue
import sys
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

from stenographer import visualizer
from stenographer.config import VisualizerConfig
from stenographer.visualizer import (
    LayerShellOverlay,
    SpectrumAnalyzer,
    _prepare_spectrum_context,
    _preview_markup,
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


def test_preview_markup_escapes_transcript_and_fades_tail() -> None:
    markup = _preview_markup("<stable & safe>", ' "tail" & <revisable>')
    assert "&lt;stable &amp; safe&gt;" in markup
    assert '"tail" &amp; &lt;revisable&gt;' in markup
    assert 'alpha="52%"' in markup
    assert 'alpha="28%"' in markup


def _started_overlay(process: MagicMock) -> LayerShellOverlay:
    """Return an overlay already bound to a fake, running helper process."""
    overlay = LayerShellOverlay(VisualizerConfig(True, 16, 80.0, 8000.0, 32))
    overlay._process = process
    overlay._started = True
    return overlay


def test_overlay_preview_and_clear_use_json_lines_protocol() -> None:
    writes: list[str] = []
    preview_written = threading.Event()

    def write(value: str) -> None:
        writes.append(value)
        # Only the preview itself may release the test: waking on any write
        # lets clear_preview() coalesce a still-pending preview away, which is
        # correct behaviour but not what this test is pinning.
        if json.loads(value).get("command") == "preview":
            preview_written.set()

    process = MagicMock()
    process.poll.return_value = None
    process.stdin.write.side_effect = write
    overlay = _started_overlay(process)

    overlay.show_preview("Stable", " tail")
    assert preview_written.wait(timeout=5.0)
    overlay.clear_preview()
    overlay.close()  # joins the writer thread, so every message has been sent

    messages = [json.loads(line) for line in writes]
    assert messages[:2] == [
        {
            "command": "preview",
            "stable": "Stable",
            "provisional": " tail",
        },
        {"command": "preview_clear"},
    ]


def test_overlay_state_supports_a_custom_notification_label() -> None:
    writes: list[str] = []
    process = MagicMock()
    process.poll.return_value = None
    process.stdin.write.side_effect = writes.append
    overlay = _started_overlay(process)

    overlay.show_state(
        "update_available",
        timeout_ms=10000,
        label="Release v1.2.3 available",
    )
    overlay.close()

    messages = [json.loads(line) for line in writes]
    assert messages[0] == {
        "command": "state",
        "state": "update_available",
        "timeout_ms": 10000,
        "label": "Release v1.2.3 available",
    }


def test_overlay_send_never_blocks_on_a_wedged_helper_pipe() -> None:
    release = threading.Event()
    process = MagicMock()
    process.poll.return_value = None
    process.stdin.write.side_effect = lambda _value: release.wait(5.0)
    overlay = _started_overlay(process)
    returned = threading.Event()

    def publish() -> None:
        for _ in range(20):
            overlay.show_levels([0.1] * 16)
            overlay.show_preview("stable", " tail")
        overlay.show_state("listening")
        returned.set()

    caller = threading.Thread(target=publish, name="test-session", daemon=True)
    caller.start()
    try:
        assert returned.wait(timeout=5.0), "overlay send blocked on the wedged helper pipe"
    finally:
        release.set()
        caller.join(timeout=5.0)
        overlay.close()


def test_overlay_coalesces_previews_when_helper_pipe_is_wedged() -> None:
    wedged = threading.Event()
    release = threading.Event()

    def write(_value: str) -> None:
        wedged.set()
        release.wait(5.0)

    process = MagicMock()
    process.poll.return_value = None
    process.stdin.write.side_effect = write
    overlay = _started_overlay(process)

    overlay.show_state("listening")
    assert wedged.wait(timeout=5.0)
    for index in range(100):
        overlay.show_preview(f"stable transcript {index}", f" tail {index}")

    with overlay._condition:
        previews = [
            message
            for message in overlay._pending
            if isinstance(message, dict) and message.get("command") == "preview"
        ]
        assert len(overlay._pending) <= overlay._QUEUE_MAXSIZE
        assert previews == [
            {
                "command": "preview",
                "stable": "stable transcript 99",
                "provisional": " tail 99",
            }
        ]

    release.set()
    overlay.close()


def test_overlay_drops_level_frames_but_never_state_or_preview() -> None:
    writes: list[str] = []
    wedged = threading.Event()
    release = threading.Event()

    def write(value: str) -> None:
        writes.append(value)
        if not wedged.is_set():
            wedged.set()
            release.wait(5.0)

    process = MagicMock()
    process.poll.return_value = None
    process.stdin.write.side_effect = write
    overlay = _started_overlay(process)

    overlay.show_levels([0.0] * 16)
    assert wedged.wait(timeout=5.0)
    for _ in range(50):
        overlay.show_levels([0.5] * 16)
    overlay.show_preview("stable", " tail")
    overlay.show_state("transcribing")
    release.set()
    overlay.close()

    commands = [json.loads(line)["command"] for line in writes]
    # At most the wedged in-flight frame plus one full queue survives.
    assert commands.count("levels") <= 5
    assert "preview" in commands
    assert "state" in commands


def test_overlay_degrades_when_helper_dies_after_ready(monkeypatch) -> None:
    terminated = threading.Event()

    class FakeStdin:
        def write(self, _value: str) -> None:
            raise BrokenPipeError("helper exited after READY")

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeStdout:
        def readline(self) -> str:
            return "READY\n"

    class FakeProcess:
        stdin = FakeStdin()
        stdout = FakeStdout()

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            terminated.set()

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(LayerShellOverlay, "probe", staticmethod(lambda: True))
    monkeypatch.setattr(visualizer.ctypes.util, "find_library", lambda _name: None)
    monkeypatch.setattr(visualizer.subprocess, "Popen", lambda *_a, **_kw: FakeProcess())
    monkeypatch.setattr(visualizer.select, "select", lambda *_args: ([object()], [], []))

    overlay = LayerShellOverlay(VisualizerConfig(True, 16, 80.0, 8000.0, 32))
    overlay.show_state("listening")

    assert terminated.wait(timeout=5.0), "a helper dying after READY was not cleaned up"
    overlay.close()
    assert overlay._unavailable


def test_overlay_startup_failure_replays_current_state_on_desktop(monkeypatch) -> None:
    desktop = MagicMock()
    fallback_shown = threading.Event()
    desktop.show_listening.side_effect = fallback_shown.set
    monkeypatch.setattr(visualizer, "DesktopNotification", lambda **_kwargs: desktop)
    monkeypatch.setattr(LayerShellOverlay, "probe", staticmethod(lambda: False))
    indicator = visualizer.StatusIndicator(cfg=VisualizerConfig(True, 16, 80.0, 8000.0, 32))

    try:
        indicator.show_listening()
        assert fallback_shown.wait(timeout=5.0)
        desktop.show_listening.assert_called_once()
        assert not indicator._analyzer._active.is_set()
    finally:
        indicator.flush()


def test_update_notification_prefers_bottom_overlay(monkeypatch) -> None:
    overlay = MagicMock()
    overlay.show_state.return_value = True
    desktop = MagicMock()
    monkeypatch.setattr(visualizer, "DesktopNotification", lambda **_kwargs: desktop)
    monkeypatch.setattr(visualizer, "LayerShellOverlay", lambda *_args, **_kwargs: overlay)
    indicator = visualizer.StatusIndicator(cfg=VisualizerConfig(True, 16, 80.0, 8000.0, 32))

    try:
        indicator.show_update_available("1.2.3")
        overlay.show_state.assert_called_once_with(
            "update_available",
            timeout_ms=10000,
            label="Release v1.2.3 available",
        )
        desktop.show_update_available.assert_not_called()
    finally:
        indicator.flush()


def test_analyzer_close_stop_survives_a_racing_submit(monkeypatch) -> None:
    parked = threading.Event()
    resume = threading.Event()
    stop_queued = threading.Event()

    class SteppedQueue(queue.Queue):
        arm = False

        def put_nowait(self, item):
            if item is visualizer._STOP:
                stop_queued.set()
            try:
                return super().put_nowait(item)
            except queue.Full:
                if SteppedQueue.arm:
                    # Park the submitting thread between its failed put and its
                    # discard-then-retry, the window close() has to survive.
                    SteppedQueue.arm = False
                    parked.set()
                    resume.wait(5.0)
                raise

    monkeypatch.setattr(visualizer.queue, "Queue", SteppedQueue)
    analyzer = SpectrumAnalyzer(
        band_count=4,
        min_frequency=80.0,
        max_frequency=8000.0,
        on_levels=lambda _levels: None,
    )
    monkeypatch.undo()

    busy = threading.Event()
    busy_release = threading.Event()

    def slow_analyze(*_args, **_kwargs):
        busy.set()
        busy_release.wait(5.0)
        return np.zeros(4, dtype=np.float32)

    monkeypatch.setattr(visualizer, "analyze_frequency_bands", slow_analyze)

    block = np.ones(1024, dtype=np.float32)
    analyzer.set_active(True)
    analyzer.submit(block, 16000)
    assert busy.wait(timeout=5.0)  # the worker is now occupied
    analyzer.submit(block, 16000)  # fills the one-slot queue
    SteppedQueue.arm = True
    submitter = threading.Thread(
        target=analyzer.submit,
        args=(block, 16000),
        name="test-audio-callback",
        daemon=True,
    )
    submitter.start()
    assert parked.wait(timeout=5.0)

    closer = threading.Thread(target=analyzer.close, name="test-close", daemon=True)
    closer.start()
    # Let close() queue its sentinel, then let the parked submit finish its
    # discard-then-retry before the worker is allowed to drain anything.
    stop_queued.wait(timeout=0.5)
    resume.set()
    submitter.join(timeout=5.0)
    busy_release.set()
    closer.join(timeout=10.0)

    assert not analyzer._worker.is_alive(), "close() lost its stop sentinel to a racing submit"


def test_analyzer_stops_publishing_when_deactivated_mid_analysis(monkeypatch) -> None:
    published: list[list[float]] = []
    analyzed = threading.Event()
    deactivate = True

    def fake_analyze(*_args, **_kwargs):
        if deactivate:
            # A cancel landing while this block is being analyzed.
            analyzer.set_active(False)
        analyzed.set()
        return np.ones(4, dtype=np.float32)

    monkeypatch.setattr(visualizer, "analyze_frequency_bands", fake_analyze)
    analyzer = SpectrumAnalyzer(
        band_count=4,
        min_frequency=80.0,
        max_frequency=8000.0,
        on_levels=published.append,
    )
    block = np.ones(1024, dtype=np.float32)
    try:
        analyzer.set_active(True)
        analyzer.submit(block, 16000)
        assert analyzed.wait(timeout=5.0)

        # Reactivate and analyze a second block. The worker is sequential, so
        # once this one is analyzed the first block is completely done with.
        deactivate = False
        analyzed.clear()
        analyzer.set_active(True)
        analyzer.submit(block, 16000)
        assert analyzed.wait(timeout=5.0)
    finally:
        analyzer.close()  # joins the worker, so every publish has landed

    # Only the second block may publish, and it must start from zeroed
    # smoothing: a cancel that got overwritten mid-update would leak through
    # as an extra frame and a carried-over level.
    assert len(published) == 1
    assert published[0] == pytest.approx([0.84] * 4, abs=1e-6)


def test_spectrum_context_is_cleared_and_clipped_each_frame() -> None:
    context = MagicMock()
    clear_operator = object()
    _prepare_spectrum_context(context, 280, 54, clear_operator=clear_operator)
    context.save.assert_called_once()
    context.set_operator.assert_called_once_with(clear_operator)
    context.paint.assert_called_once()
    context.restore.assert_called_once()
    context.rectangle.assert_called_once_with(0, 0, 280, 54)
    context.clip.assert_called_once()


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

        def close(self) -> None:
            pass

        def readline(self) -> str:
            return "READY\n"

    class FakeProcess:
        stdin = FakeStream()
        stdout = FakeStream()

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

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
    overlay.close()  # joins the writer thread, which owns the helper spawn
    assert captured_environment["LD_PRELOAD"].split(":")[0] == ("libgtk4-layer-shell.so.0")
    assert captured_environment["STENOGRAPHER_FONT_PATH"] == str(font_path)
