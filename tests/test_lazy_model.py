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
        "vad_filter": True,
        "max_new_tokens": 128,
        "mode": "lazy",
        "idle_unload_seconds": 300,
        "hotwords": None,
        "initial_prompt": None,
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

    def test_ensure_loaded_retries_after_a_failed_load(self) -> None:
        # A failed load also sets _loaded_event (so _await_impl waiters wake and
        # see the exception), but leaves _impl None. Gating on the event would
        # make this a permanent no-op while is_loaded() keeps reporting False:
        # the caller registers a callback that never fires and shows a
        # model-loading notification that nothing ever resolves.
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        m._loaded_event.set()
        m._load_exception = RuntimeError("first load failed")
        on_loaded = MagicMock()
        started = threading.Event()

        def fake_do_load() -> None:
            started.set()

        with patch.object(m, "_do_load", side_effect=fake_do_load):
            m.ensure_loaded(on_loaded=on_loaded)
            assert started.wait(2.0), "a failed load must be retried, not skipped"
        assert m._on_loaded_cb is on_loaded
        assert m._load_exception is None, "the stale exception must not outlive the retry"


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

    def test_transcribe_words_delegates_and_reschedules_unload(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=300)
        fake_impl = MagicMock()
        fake_impl.transcribe_words.return_value = []
        m._impl = fake_impl  # type: ignore[assignment]
        m._loaded_event.set()
        gen = m._load_generation
        with patch.object(m, "_schedule_unload") as schedule:
            words = m.transcribe_words(np.zeros(100, dtype=np.float32), beam_size=2)
        assert words == []
        fake_impl.transcribe_words.assert_called_once()
        assert fake_impl.transcribe_words.call_args.kwargs["beam_size"] == 2
        assert m._load_generation == gen + 1
        schedule.assert_called_once()

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


class TestWorkerThreadUnload:
    """The idle-unload timer routes disposal onto the Worker thread, where
    CTranslate2 bound the model; a generation counter drops stale requests."""

    def test_attach_worker_stores_weakref(self) -> None:
        import gc as _gc

        m = LazyModel(_cfg(), idle_unload_seconds=1)
        worker = MagicMock(spec=["request_unload", "is_alive"])
        m.attach_worker(worker)
        assert m._worker_ref is not None
        assert m._worker_ref() is worker
        del worker
        _gc.collect()
        assert m._worker_ref() is None

    def test_request_unload_via_worker_calls_worker_request_unload(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        worker = MagicMock(spec=["request_unload", "is_alive"])
        m.attach_worker(worker)
        m._loaded_event.set()
        gen = m._load_generation
        m._request_unload_via_worker()
        worker.request_unload.assert_called_once_with(gen)

    def test_request_unload_via_worker_falls_back_to_unload_without_worker(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        # No attach_worker: should fall back to _unload (drops _impl).
        m._request_unload_via_worker()
        assert m._impl is None
        assert not m._loaded_event.is_set()

    def test_do_unload_on_worker_matching_token_drops_model(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        m.do_unload_on_worker(m._load_generation)
        assert m._impl is None
        assert not m._loaded_event.is_set()

    def test_do_unload_on_worker_stale_token_skips(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=1)
        m._loaded_event.set()
        m._impl = MagicMock()  # type: ignore[assignment]
        # A transcribe happened after the timer fired, bumping the generation.
        m._load_generation += 1
        m.do_unload_on_worker(token=0)
        assert m._impl is not None
        assert m._loaded_event.is_set()

    def test_transcribe_bumps_load_generation(self) -> None:
        m = LazyModel(_cfg(), idle_unload_seconds=3600)
        fake_impl = MagicMock()
        fake_impl.transcribe.return_value = TranscriptionResult(text="x", duration_seconds=0.0)
        m._impl = fake_impl  # type: ignore[assignment]
        m._loaded_event.set()
        gen0 = m._load_generation
        m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        assert m._load_generation == gen0 + 1
        m._unload_timer.cancel()

    def test_worker_run_handles_unload_sentinel(self) -> None:
        """Worker._run dequeues the _UNLOAD sentinel and calls
        do_unload_on_worker(token) on a LazyModel, then trims the arena."""
        from stenographer.asr import worker as worker_mod
        from stenographer.asr.worker import Worker

        model = MagicMock(spec=LazyModel)
        worker = Worker(model)
        worker.start()
        try:
            with patch.object(worker_mod, "_trim_arena") as trim:
                worker.request_unload(token=7)
                # Wait for the worker to process the sentinel.
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if model.do_unload_on_worker.called and trim.called:
                        break
                    time.sleep(0.02)
                model.do_unload_on_worker.assert_called_once_with(7)
                trim.assert_called_once()
        finally:
            worker.stop(timeout=2.0)


class TestProperties:
    def test_language_property(self) -> None:
        m = LazyModel(_cfg(language="en"))
        assert m.language == "en"

    def test_beam_size_property(self) -> None:
        m = LazyModel(_cfg(beam_size=3))
        assert m.beam_size == 3


class TestVocabularyBias:
    """asr.hotwords / asr.initial_prompt must reach both faster-whisper calls."""

    def _model(self, **cfg_overrides: object):
        from stenographer.asr.model import Model

        with patch("stenographer.asr.model.WhisperModel") as whisper_cls:
            m = Model(_cfg(**cfg_overrides))
        fake = whisper_cls.return_value
        fake.transcribe.return_value = (
            [],
            MagicMock(duration=0.0, duration_after_vad=0.0),
        )
        return m, fake

    def test_transcribe_forwards_hotwords_and_initial_prompt(self) -> None:
        m, fake = self._model(hotwords="wtype, Wayland", initial_prompt="Arch Linux notes.")
        m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        kwargs = fake.transcribe.call_args.kwargs
        assert kwargs["hotwords"] == "wtype, Wayland"
        assert kwargs["initial_prompt"] == "Arch Linux notes."

    def test_transcribe_words_forwards_hotwords_and_initial_prompt(self) -> None:
        m, fake = self._model(hotwords="wtype, Wayland", initial_prompt="Arch Linux notes.")
        m.transcribe_words(np.zeros(100, dtype=np.float32))
        kwargs = fake.transcribe.call_args.kwargs
        assert kwargs["hotwords"] == "wtype, Wayland"
        assert kwargs["initial_prompt"] == "Arch Linux notes."

    def test_unset_vocabulary_passes_none(self) -> None:
        m, fake = self._model()
        m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        kwargs = fake.transcribe.call_args.kwargs
        assert kwargs["hotwords"] is None
        assert kwargs["initial_prompt"] is None

    def test_transcribe_forwards_silence_hardening(self) -> None:
        m, fake = self._model(vad_filter=True, max_new_tokens=128, silence_threshold=0.7)
        m.transcribe(np.zeros(100, dtype=np.float32), "en", 1)
        kwargs = fake.transcribe.call_args.kwargs
        assert kwargs["vad_filter"] is True
        assert kwargs["vad_parameters"] == {
            "threshold": 0.5,
            "min_speech_duration_ms": 100,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 250,
        }
        assert kwargs["no_speech_threshold"] == 0.7
        assert kwargs["hallucination_silence_threshold"] == 2.0
        assert kwargs["max_new_tokens"] == 128
        assert kwargs["word_timestamps"] is True

    def test_transcribe_words_forwards_silence_hardening(self) -> None:
        m, fake = self._model(vad_filter=False, max_new_tokens=64, silence_threshold=0.5)
        m.transcribe_words(np.zeros(100, dtype=np.float32))
        kwargs = fake.transcribe.call_args.kwargs
        assert kwargs["vad_filter"] is False
        assert kwargs["vad_parameters"]["min_speech_duration_ms"] == 100
        assert kwargs["no_speech_threshold"] == 0.5
        assert kwargs["hallucination_silence_threshold"] == 2.0
        assert kwargs["max_new_tokens"] == 64
        assert kwargs["word_timestamps"] is True


class TestLoadFailure:
    def test_is_loaded_false_after_load_failure(self) -> None:
        """A failed load must not report as loaded.

        _do_load sets _loaded_event on the failure path so _await_impl waiters
        wake up and see the exception -- but _impl stays None. Reporting that
        as loaded makes Session skip its "loading model" notification and its
        on_loaded registration, so the user gets no feedback at all on the
        utterance that fails.
        """
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        with patch("stenographer.asr.model.Model", side_effect=RuntimeError("corrupt model dir")):
            m.ensure_loaded()
            assert m._load_thread is not None
            m._load_thread.join(timeout=2.0)
        assert m._load_exception is not None, "precondition: the load must have failed"
        assert not m.is_loaded()

    def test_await_impl_does_not_clobber_registered_on_loaded(self) -> None:
        """_await_impl calls ensure_loaded() with no arguments.

        An unconditional `self._on_loaded_cb = on_loaded` therefore deregisters
        the session's callback, and the "model ready" cue never fires for the
        reload after an idle unload -- the user holds the hotkey waiting for a
        cue that never comes.
        """
        m = LazyModel(_cfg(), idle_unload_seconds=0)
        on_loaded = MagicMock()
        m.ensure_loaded(on_loaded=on_loaded)
        assert m._on_loaded_cb is on_loaded
        # The state _await_impl finds after an idle unload: the event is clear
        # and the previous loader thread is gone, so its no-arg ensure_loaded()
        # falls past both early returns and reaches the callback assignment.
        # (Without this setup the live-thread early return hides the defect and
        # the test passes against unfixed code.)
        m._loaded_event.clear()
        m._load_thread = None
        with patch("stenographer.asr.model.Model", side_effect=RuntimeError("boom")):
            m.ensure_loaded()  # the no-arg call _await_impl makes
            if m._load_thread is not None:
                m._load_thread.join(timeout=2.0)
        assert m._on_loaded_cb is on_loaded
