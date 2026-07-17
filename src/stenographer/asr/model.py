# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import os
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from faster_whisper import WhisperModel

if TYPE_CHECKING:
    from stenographer.asr.worker import Worker
    from stenographer.config import AsrConfig

log = logging.getLogger(__name__)


def _read_rss_kb() -> int | None:
    """Return current VmRSS in kB from ``/proc/self/status`` (Linux only).

    Used only by the opt-in ``STENOGRAPHER_TRACE_UNLOAD`` tracing path.
    Returns ``None`` if not available (non-Linux or unreadable).
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError, ValueError, IndexError:
        return None
    return None


@dataclass(frozen=True)
class SegmentInfo:
    start: float
    end: float
    text: str
    no_speech_prob: float


@dataclass(frozen=True)
class WordInfo:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: float
    segments: list[SegmentInfo] = field(default_factory=list)


class Model:
    def __init__(self, cfg: AsrConfig) -> None:
        log.info("loading ASR model: id=%s compute_type=%s", cfg.model, cfg.compute_type)
        self._impl = WhisperModel(
            cfg.model,
            device="auto",
            compute_type=cfg.compute_type,
        )
        self._language = cfg.language
        self._beam_size = cfg.beam_size
        log.info("ASR model loaded: %s", cfg.model)

    @property
    def language(self) -> str:
        return self._language

    @property
    def beam_size(self) -> int:
        return self._beam_size

    def transcribe(
        self,
        samples: np.ndarray,
        language: str,
        beam_size: int,
        on_segment: Callable[[SegmentInfo], None] | None = None,
    ) -> TranscriptionResult:
        if samples.size == 0:
            return TranscriptionResult(text="", duration_seconds=0.0, segments=[])
        if samples.ndim == 2 and samples.shape[1] == 1:
            samples = samples.squeeze(-1)
        segments_iter, info = self._impl.transcribe(
            samples,
            language=language,
            beam_size=beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        seg_infos: list[SegmentInfo] = []
        for seg in segments_iter:
            si = SegmentInfo(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                no_speech_prob=seg.no_speech_prob,
            )
            if on_segment is not None:
                on_segment(si)
            seg_infos.append(si)
        text = "".join(seg.text for seg in seg_infos).strip()
        return TranscriptionResult(
            text=text,
            duration_seconds=info.duration,
            segments=seg_infos,
        )

    def transcribe_words(
        self,
        samples: np.ndarray,
        *,
        beam_size: int | None = None,
        check_cancel: Callable[[], None] | None = None,
    ) -> list[WordInfo]:
        """Low-level word-timestamped transcription for the live streaming path.

        Unlike :meth:`transcribe` (the batch daemon path, left untouched),
        this requests ``word_timestamps=True``.  *check_cancel* is invoked
        once per decoded segment so an in-flight re-decode can be aborted
        (it should raise to abort).  Returns a flat, time-ordered list of
        words.
        """
        if samples.size == 0:
            return []
        if samples.ndim == 2 and samples.shape[1] == 1:
            samples = samples.squeeze(-1)
        segments_iter, _info = self._impl.transcribe(
            samples,
            language=self._language,
            beam_size=self._beam_size if beam_size is None else beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
        words: list[WordInfo] = []
        for seg in segments_iter:
            if check_cancel is not None:
                check_cancel()
            for w in seg.words or ():
                words.append(
                    WordInfo(start=w.start, end=w.end, word=w.word, probability=w.probability)
                )
        return words

    def close(self) -> None:
        if hasattr(self, "_impl"):
            del self._impl


class LazyModel:
    """Wraps :class:`Model`, deferring ``WhisperModel`` construction.

    Used by the daemon when ``cfg.asr.mode == "lazy"``.  The session
    calls :meth:`ensure_loaded` (non-blocking) on the first hotkey
    press; the first :meth:`transcribe` blocks until the inner
    :class:`Model` is constructed.

    Idle unload: after *idle_unload_seconds* without a
    :meth:`transcribe` call the inner :class:`Model` is dropped and
    ``gc.collect()`` is called to reclaim GPU / CPU memory.
    """

    def __init__(
        self,
        cfg: AsrConfig,
        idle_unload_seconds: float | None = None,
    ) -> None:
        self._cfg = cfg
        self._idle_unload_seconds = idle_unload_seconds
        self._lock = threading.RLock()
        self._impl: Model | None = None
        self._loaded_event = threading.Event()
        self._load_thread: threading.Thread | None = None
        self._on_loaded_cb: Callable[[], None] | None = None
        self._on_unloaded_cb: Callable[[], None] | None = None
        self._unload_timer: threading.Timer | None = None
        self._load_exception: BaseException | None = None
        self._worker_ref: weakref.ref[Worker] | None = None
        self._load_generation: int = 0

    @property
    def language(self) -> str:
        return self._cfg.language

    @property
    def beam_size(self) -> int:
        return self._cfg.beam_size

    def attach_worker(self, worker: Worker) -> None:
        """Stash a weakref to the owning Worker so the idle-unload timer
        can route model disposal onto the worker thread (where the
        CTranslate2 ReplicaPool binding lives).  Called once by the
        CLI after both objects are constructed.
        """
        self._worker_ref = weakref.ref(worker)

    def ensure_loaded(
        self,
        on_loaded: Callable[[], None] | None = None,
        on_unloaded: Callable[[], None] | None = None,
    ) -> None:
        """Start loading the inner Model on a background thread.

        Idempotent: returns immediately if the model is already
        loaded or currently loading.  *on_loaded* fires on the
        loader thread exactly once after the model becomes available
        (or re-available after an idle unload).  *on_unloaded* fires
        on the timer thread when idle unload completes.

        Gated on ``_impl``, not on ``_loaded_event``: a failed load also sets
        the event, so gating on it would make this a no-op forever after the
        first failure while :meth:`is_loaded` kept reporting False -- the
        caller would register a callback that never fires and wait on a load
        that never starts. A failed load is therefore retried here.
        """
        with self._lock:
            if self._impl is not None:
                return
            if self._load_thread is not None and self._load_thread.is_alive():
                return
            self._loaded_event.clear()
            self._load_exception = None
            # Guarded like _on_unloaded_cb below: _await_impl() calls this with
            # no arguments, so an unconditional assignment would silently
            # deregister the session's callback and the "model ready" cue would
            # never fire for the reload after an idle unload.
            if on_loaded is not None:
                self._on_loaded_cb = on_loaded
            if on_unloaded is not None:
                self._on_unloaded_cb = on_unloaded
            self._load_thread = threading.Thread(
                target=self._do_load,
                name="asr-model-loader",
                daemon=True,
            )
            self._load_thread.start()

    def is_loaded(self) -> bool:
        """Whether the inner Model is actually available right now.

        Not ``_loaded_event.is_set()``: that event means "the load finished",
        which a *failed* load also satisfies (it is set so waiters in
        :meth:`_await_impl` can wake up and see the exception). Reporting a
        failed load as loaded makes the session skip its model-loading
        notification and callback registration, so the user gets no feedback
        at all on the utterance that fails.
        """
        with self._lock:
            return self._impl is not None

    def close(self) -> None:
        """Cancel the idle-unload timer.  Does NOT unload the model."""
        with self._lock:
            if self._unload_timer is not None:
                self._unload_timer.cancel()
                self._unload_timer = None

    def transcribe(
        self,
        samples: np.ndarray,
        language: str,
        beam_size: int,
        on_segment: Callable[[SegmentInfo], None] | None = None,
    ) -> TranscriptionResult:
        """Wait until the model is loaded (blocking), then run inference.

        Reschedules the idle-unload timer on every successful call.
        """
        impl = self._await_impl()
        result = impl.transcribe(samples, language, beam_size, on_segment=on_segment)
        self._load_generation += 1
        self._schedule_unload()
        return result

    def transcribe_words(
        self,
        samples: np.ndarray,
        *,
        beam_size: int | None = None,
        check_cancel: Callable[[], None] | None = None,
    ) -> list[WordInfo]:
        """Wait until the model is loaded (blocking), then run a word decode.

        Reschedules the idle-unload timer on every successful call.
        """
        impl = self._await_impl()
        result = impl.transcribe_words(samples, beam_size=beam_size, check_cancel=check_cancel)
        self._load_generation += 1
        self._schedule_unload()
        return result

    # -- internal -------------------------------------------------------

    def _await_impl(self) -> Model:
        """Block until the inner Model is loaded and return it.

        Re-raises a stored load exception (clearing state so a later
        call retries the load).
        """
        while True:
            if not self._loaded_event.is_set():
                self.ensure_loaded()
            self._loaded_event.wait()
            with self._lock:
                if not self._loaded_event.is_set():
                    continue
                if self._load_exception is not None:
                    exc = self._load_exception
                    self._load_exception = None
                    self._load_thread = None
                    self._loaded_event.clear()
                    raise exc
                impl = self._impl
            assert impl is not None
            return impl

    def _do_load(self) -> None:
        try:
            log.info(
                "loading ASR model: id=%s compute_type=%s",
                self._cfg.model,
                self._cfg.compute_type,
            )
            impl = Model(self._cfg)
            with self._lock:
                self._impl = impl
                self._load_exception = None
                cb = self._on_loaded_cb
            self._loaded_event.set()
            log.info("ASR model loaded: %s", self._cfg.model)
            if cb is not None:
                try:
                    cb()
                except Exception as exc:
                    log.error("LazyModel: on_loaded callback failed: %s", exc)
            self._schedule_unload()
        except BaseException as exc:
            log.exception("ASR model load failed")
            with self._lock:
                self._load_exception = exc
                self._load_thread = None
            self._loaded_event.set()

    def _schedule_unload(self) -> None:
        if self._idle_unload_seconds is None or self._idle_unload_seconds <= 0:
            return
        with self._lock:
            if self._unload_timer is not None:
                self._unload_timer.cancel()
            self._unload_timer = threading.Timer(
                self._idle_unload_seconds, self._request_unload_via_worker
            )
            self._unload_timer.daemon = True
            self._unload_timer.name = "asr-model-unload"
            self._unload_timer.start()

    def _request_unload_via_worker(self) -> None:
        """Fire on the timer thread. Hands the actual disposal off to
        the Worker thread via a sentinel job; the Worker thread is
        where CTranslate2's ReplicaPool bound the model, so dropping
        it there is what lets the C++ destructor release the weights.
        Falls back to in-timer-thread ``_unload`` only if the Worker
        has gone away (defensive; should not happen in normal life).
        """
        gen = self._load_generation
        worker_ref = self._worker_ref
        worker = worker_ref() if worker_ref is not None else None
        if worker is not None:
            worker.request_unload(gen)
        else:
            self._unload()

    def do_unload_on_worker(self, token: int) -> None:
        """Run on the Worker thread. Drops the model iff *token* matches
        the current ``_load_generation`` (a transcribe that happened
        between the timer firing and the Worker dequeuing the request
        would have bumped the generation, invalidating this token).
        """
        with self._lock:
            if token != self._load_generation:
                log.debug(
                    "ASR model: unload request stale (token=%s gen=%s), skipping",
                    token,
                    self._load_generation,
                )
                return
        self._unload()

    def _unload(self) -> None:
        trace = __debug__ and os.environ.get("STENOGRAPHER_TRACE_UNLOAD") == "1"
        with self._lock:
            impl = self._impl
            self._impl = None
            self._loaded_event.clear()
            self._unload_timer = None
        if impl is not None:
            log.info(
                "ASR model: unloading after %s s idle",
                self._idle_unload_seconds,
            )
            if trace:
                import gc as _gc

                whisper = getattr(impl, "_impl", None)
                referrers = (
                    [type(r).__name__ for r in _gc.get_referrers(whisper)]
                    if whisper is not None
                    else ["<no _impl attr>"]
                )
                rss0 = _read_rss_kb()
                log.info(
                    "trace-unload: before close referrers=%s rss_kb=%s",
                    referrers,
                    rss0,
                )
                _gc.collect()
            try:
                impl.close()
            except Exception as exc:
                log.error("ASR model: close during unload failed: %s", exc)
            del impl
            import gc

            gc.collect()
        cb = self._on_unloaded_cb
        if cb is not None:
            try:
                cb()
            except Exception as exc:
                log.error("LazyModel: on_unloaded callback failed: %s", exc)
