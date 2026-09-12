# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared injected collaborators for the real daemon policy.

No stand-in mocks native calls: lifecycle, processing, measurements, and summary
rendering all execute the shipping implementation. Native behavior remains
covered by the real-machine acceptance tests.
"""

from __future__ import annotations

import dataclasses
import logging
import threading

import numpy as np
import pytest

from stenographer.lib.audio.records import CaptureStats
from stenographer.lib.config.models import Config
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.daemon import Daemon
from stenographer.lib.daemon.feedback import _play_cue
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.daemon.policy import cancel_state
from stenographer.lib.delivery.timings import DeliveryTimings
from stenographer.lib.logging.utterance_filter import UtteranceFilter
from stenographer.lib.platform.errors import UnsupportedPlatformError
from stenographer.lib.refine.cancellation import never_cancelled
from stenographer.lib.refine.policy import should_refine
from stenographer.lib.refine.results import OUTCOME_APPLIED, RefineResult
from stenographer.lib.transcribe.results import TranscriptionResult
from stenographer.lib.transcribe.worker_timings import WorkerTimings

# Never a substring of any field name, level, subsystem, or path in the log.
CANARY = "supercalifragilisticexpialidocious"

_RATE = 16000
_SPEECH = np.full(_RATE, 0.02, dtype=np.float32)
_SILENCE = np.zeros(_RATE, dtype=np.float32)
_CAPTURE = CaptureStats(
    activate_ms=3.0,
    capture_seconds=1.0,
    input_frames=_RATE,
    output_frames=_RATE,
    overflow=False,
    capped=False,
)


def _no_network_cfg(cfg: Config | None = None) -> Config:
    """A daemon config guaranteed not to reach Ollama.

    Refine now defaults to enabled, so building a daemon straight from
    ``cfg.refine`` gives it a live ``OllamaRefiner``; that refiner's own
    ``unload()`` runs unconditionally in ``Daemon.stop()``, not only on the
    warm-up path, so any test that builds a real daemon and stops it hits the
    network unless refine is off. Every daemon test that is not itself about
    refine behaviour routes through this (directly, or via ``_build_or_skip``)
    so the suite never touches Ollama. Tests that want a live refiner pass
    ``refiner=`` explicitly instead of relying on ``cfg.refine``.
    """
    cfg = cfg if cfg is not None else Config.defaults()
    return dataclasses.replace(cfg, refine=dataclasses.replace(cfg.refine, enabled=False))


def _build_or_skip(cfg):
    """Build for real, or skip where the host provides no hotkey/paste backend.

    Expressed as a capability rather than an OS name so a provider that grows
    a real backend starts running these checks without touching the test.
    """
    from stenographer.lib.daemon.daemon import Daemon

    try:
        return Daemon.build(_no_network_cfg(cfg), clipboard_backend="wl-copy")
    except UnsupportedPlatformError as exc:
        pytest.skip(f"no hotkey/injection backend on this host: {exc}")


class _Feedback:
    def __init__(self) -> None:
        self.cues: list[str] = []

    def play(self, name: str) -> None:
        self.cues.append(name)

    def close(self) -> None: ...


class _Notifier:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def info(self, message: str) -> None: ...


class _Recorder:
    def __init__(self, samples: np.ndarray) -> None:
        self._samples = samples
        self.last_capture: CaptureStats | None = None

    def start(self) -> None:
        self.last_capture = None

    def stop(self) -> np.ndarray:
        self.last_capture = _CAPTURE
        return self._samples

    def prepare(self) -> None: ...

    def close(self) -> None: ...


class _Worker:
    def __init__(self, result: TranscriptionResult | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.last_timings: WorkerTimings | None = None
        self.utterances: list[int | None] = []
        self.is_model_ready = False
        self.transcribe_started = threading.Event()
        self.transcribe_release = threading.Event()
        self.block_transcribe = False

    def hold_model(self) -> None: ...

    def release_model(self) -> None: ...

    def warmup(self, utterance: int | None = None) -> None: ...

    def shutdown(self) -> None: ...

    def transcribe(self, samples: np.ndarray, utterance: int | None = None) -> TranscriptionResult:
        self.utterances.append(utterance)
        self.transcribe_started.set()
        if self.block_transcribe:
            self.transcribe_release.wait(timeout=10.0)
        if self._error is not None:
            raise self._error
        self.last_timings = WorkerTimings(lock_wait_ms=0.5, load_ms=900.0, decode_ms=1500.0)
        self.is_model_ready = True
        return self._result


class _Refiner:
    """Refiner double: no Ollama, no network, the real contract.

    Constructed with what the stage should do (return a string, or raise), so
    a pipeline test can prove the fallback without pretending to be a server.
    """

    def __init__(
        self,
        *,
        refined: str | None = None,
        error: Exception | None = None,
        min_words: int = 10,
        outcome: str = OUTCOME_APPLIED,
        measurement_error: Exception | None = None,
        unload_error: Exception | None = None,
    ) -> None:
        self._refined = refined
        self._error = error
        self._min_words = min_words
        self._outcome = outcome
        self._measurement_error = measurement_error
        self._unload_error = unload_error
        self._last_result: RefineResult | None = None
        self.calls: list[str] = []
        self.unloaded = 0
        self.on_refine = None

    def unload(self) -> None:
        self.unloaded += 1
        if self._unload_error is not None:
            raise self._unload_error

    @property
    def last_result(self) -> RefineResult | None:
        # Reading a measurement is a call into the collaborator too, so it has
        # to be breakable independently of ``refine`` itself.
        if self._measurement_error is not None:
            raise self._measurement_error
        return self._last_result

    def will_refine(self, text: str) -> bool:
        return should_refine(text, self._min_words)

    def refine(self, text: str, *, cancelled=never_cancelled) -> str:
        self.calls.append(text)
        if self.on_refine is not None:
            self.on_refine()
        if self._error is not None:
            # A real refiner swallows its own failures; this one is also used
            # to prove the pipeline survives one that does not.
            raise self._error
        refined = self._refined if self._refined is not None else text
        self._last_result = RefineResult(
            self._outcome,
            chars_in=len(text),
            chars_out=len(refined),
            duration_ms=12.0,
        )
        return refined


class _Deliverer:
    def __init__(self) -> None:
        self.delivered: list[str] = []
        self.last_timings: DeliveryTimings | None = None

    def deliver(self, text: str, *, on_copied=None, cancelled=None) -> bool:
        self.delivered.append(text)
        self.last_timings = DeliveryTimings(
            copy_ms=8.0, release_wait_ms=30.0, release_timeout=False
        )
        return True

    def close(self) -> None: ...


def _daemon(*, result=None, error=None, samples=_SPEECH, mode="hold", refiner=None) -> Daemon:
    cfg = _no_network_cfg()
    cfg = dataclasses.replace(cfg, hotkey=dataclasses.replace(cfg.hotkey, mode=mode))
    daemon = Daemon(
        cfg=cfg,
        feedback=_Feedback(),
        notifier=_Notifier(),
        worker=_Worker(result, error),
        recorder=_Recorder(samples),
    )
    daemon._deliverer = _Deliverer()
    if refiner is not None:
        daemon._refiner = refiner
    daemon._pipeline = UtterancePipeline(
        min_speech_rms=cfg.audio.min_speech_rms,
        worker=daemon._worker,
        deliverer=daemon._deliverer,
        refiner=daemon._refiner,
        telemetry=daemon._telemetry,
        publish_state=daemon._publish_state,
        fail=daemon._fail,
        play_cue=lambda name: _play_cue(daemon._feedback, name),
        cancelled=daemon._cancel_pending,
        cancel_state=lambda: cancel_state(shutting_down=daemon._stop_event.is_set()),
    )
    return daemon


def _run_utterance(daemon: Daemon) -> None:
    daemon.on_key_down()
    daemon.on_key_up()
    thread = daemon._pipeline_thread
    if thread is not None:
        thread.join(timeout=10.0)
        assert not thread.is_alive()


def _summary(caplog) -> str:
    lines = [m for m in caplog.messages if m.startswith("pipeline: utterance ")]
    assert len(lines) == 1, caplog.messages
    return lines[0]


def _current_stamp() -> str:
    """What ``UtteranceFilter`` would stamp on a record emitted right now."""
    record = logging.getLogger("stenographer.lib.daemon").makeRecord(
        "stenographer.lib.daemon", logging.INFO, __file__, 0, "probe: stamp", (), None
    )
    UtteranceFilter().filter(record)
    return record.utt_suffix


class _Status:
    """Records every lifecycle state the daemon hands to the pill, in order."""

    def __init__(self) -> None:
        self.states: list[OverlayState] = []
        self.loading: list[bool] = []

    def publish(self, state: OverlayState) -> int:
        self.states.append(state)
        return len(self.states)

    def loading_activity(self, active: bool) -> None:
        self.loading.append(active)


def _daemon_with_status(
    *, result=None, samples=_SPEECH, warm=True, refiner=None
) -> tuple[Daemon, _Status]:
    daemon = _daemon(result=result, samples=samples, refiner=refiner)
    daemon._worker.is_model_ready = warm
    status = _Status()
    daemon._status = status
    return daemon, status


class _KeyInjector:
    """Injection double: records chords instead of opening ``/dev/uinput``."""

    def __init__(self) -> None:
        self.chords = 0
        self.closed = False

    def send_chord(self) -> None:
        self.chords += 1

    def close(self) -> None:
        self.closed = True


class _Listener:
    """Retains the wiring ``Daemon.build`` hands the host; starts and stops for real."""

    def __init__(
        self,
        *,
        chord,
        device,
        on_start,
        on_stop,
        lock,
        cancel=frozenset(),
        on_cancel=None,
    ) -> None:
        self.chord = chord
        self.device = device
        self.cancel = cancel
        self.lock = lock
        self._on_start = on_start
        self._on_stop = on_stop
        self.on_cancel = on_cancel
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self) -> None:
        self.started.set()

    def stop(self) -> None:
        self.stopped.set()

    def wait_binding_released(self, timeout: float | None = None) -> bool:
        return True


class _Platform:
    """Host double for ``Daemon.build``: inert backends, real key vocabulary."""

    name = "test"

    def __init__(self) -> None:
        self.listener: _Listener | None = None
        self.injector = _KeyInjector()
        self.notifier_double = _Notifier()
        self.clipboard_backends: list[str] = []
        self.copied: list[str] = []

    def cue_player(self):
        return None

    def notifier(self):
        return self.notifier_double

    def asr_transport(self):
        return None

    def keys(self):
        from stenographer.lib.hotkey.static_key_table import StaticKeyTable

        return StaticKeyTable()

    def hotkey_listener(self, **wiring):
        self.listener = _Listener(**wiring)
        return self.listener

    def key_injector(self):
        return self.injector

    def clipboard_writer(self, backend: str):
        self.clipboard_backends.append(backend)

        def copy(text: str) -> bool:
            self.copied.append(text)
            return True

        return copy
