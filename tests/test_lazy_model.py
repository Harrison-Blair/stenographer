# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for :class:`stenographer.asr.model.LazyModel`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from stenographer.asr.model import LazyModel, TranscriptionResult
from stenographer.config import AsrConfig


def _cfg(**overrides: object) -> AsrConfig:
    defaults: dict[str, object] = {
        "model": "Systran/faster-whisper-large-v3",
        "language": "en",
        "beam_size": 1,
        "compute_type": "int8",
        "silence_threshold": 0.6,
        "mode": "lazy",
        "idle_unload_seconds": 3600,
    }
    defaults.update(overrides)
    return AsrConfig(**defaults)  # type: ignore[arg-type]


class TestEnsureLoaded:
    def test_is_loaded_false_initially(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        assert not m.is_loaded()

    def test_ensure_loaded_idempotent(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        on_loaded = MagicMock()
        started = threading.Event()

        def fake_do_load():
            started.set()
            while True:
                time.sleep(0.01)

        with patch.object(m, "_do_load", side_effect=fake_do_load):
            m.ensure_loaded(on_loaded=on_loaded)
            started.wait(timeout=1.0)
            m.ensure_loaded(on_loaded=on_loaded)
            assert m._load_thread is not None
            assert m._load_thread.is_alive()
            # the timer is still running from the first call;
            # no second thread was started

    def test_ensure_loaded_stores_callbacks(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        on_loaded = MagicMock()
        on_unloaded = MagicMock()
        m.ensure_loaded(on_loaded=on_loaded, on_unloaded=on_unloaded)
        assert m._on_loaded_cb is on_loaded
        assert m._on_unloaded_cb is on_unloaded

    def test_ensure_loaded_ignores_when_already_loaded(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        with patch.object(m, "_do_load") as do_load:
            m.ensure_loaded()
            do_load.assert_not_called()


class TestTranscribe:
    def test_transcribe_blocks_until_loaded(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        fake_result = TranscriptionResult(text="hi", duration_seconds=0.1)

        def fake_load():
            time.sleep(0.05)
            m._impl = MagicMock()
            m._impl.transcribe.return_value = fake_result  # type: ignore[union-attr]
            m._loaded_event.set()

        t = threading.Thread(target=fake_load, daemon=True)
        t.start()
        result = m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        assert result.text == "hi"

    def test_transcribe_after_loaded(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        fake_impl = MagicMock()
        fake_impl.transcribe.return_value = TranscriptionResult(text="ok", duration_seconds=0.0)
        m._impl = fake_impl  # type: ignore[assignment]
        m._loaded_event.set()
        result = m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        assert result.text == "ok"
        fake_impl.transcribe.assert_called_once()

    def test_transcribe_raises_stored_load_exception(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        m._load_exception = RuntimeError("load failed")
        m._loaded_event.set()
        with pytest.raises(RuntimeError, match="load failed"):
            m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        assert not m._loaded_event.is_set()


class TestIdleUnload:
    def test_schedule_unload_starts_timer(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._schedule_unload()
        assert m._unload_timer is not None
        assert m._unload_timer.is_alive()
        m._unload_timer.cancel()

    def test_unload_drops_model_and_clears_event(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._unload()
        assert m._impl is None
        assert not m._loaded_event.is_set()

    def test_unload_fires_callback(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        cb = MagicMock()
        m._on_unloaded_cb = cb
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._unload()
        cb.assert_called_once()

    def test_transcribe_resets_timer(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=3600)
        fake_impl = MagicMock()
        fake_impl.transcribe.return_value = TranscriptionResult(text="x", duration_seconds=0.0)
        m._impl = fake_impl  # type: ignore[assignment]
        m._loaded_event.set()
        m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        assert m._unload_timer is not None
        assert isinstance(m._unload_timer, threading.Timer)
        m._unload_timer.cancel()

    def test_idle_unload_seconds_none_disables_timer(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=None)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._schedule_unload()
        assert m._unload_timer is None

    def test_idle_unload_seconds_zero_disables_timer(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._schedule_unload()
        assert m._unload_timer is None

    def test_close_cancels_timer(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=60)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m._schedule_unload()
        assert m._unload_timer is not None
        m.close()
        assert m._unload_timer is None


class TestProperties:
    def test_language_property(self) -> None:
        m = LazyModel(_cfg(language="en"))
        assert m.language == "en"

    def test_beam_size_property(self) -> None:
        m = LazyModel(_cfg(beam_size=3))
        assert m.beam_size == 3
