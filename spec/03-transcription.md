<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 03 — Transcription

## Dependencies

- **Reads:** `00-overview.md` (Worker definition).
- **Reads:** `07-configuration.md` (`asr.*` keys).
- **Reads:** `09-error-handling.md` (runtime error policy, capability matrix).
- **Reads:** `10-packaging.md` (`faster-whisper` dep, model cache location).
- **Consumes:** `numpy.ndarray` buffer from `02-audio-capture.md`.
- **Blocks:** `05-text-output.md` and `06-clipboard.md` receive the
  transcript from the Worker.
- **Blocks:** `08-process-model.md` constructs the Worker.

## Goal

Specify the `Worker` component: a long-lived background thread that
owns the faster-whisper model, accepts buffers from the `Session`, and
returns a final transcript string per utterance. v1 is local-only,
English-only, single utterance at a time.

## Engine

- Library: `faster-whisper` (CTranslate2 backend).
- Model: `cfg.asr.model` (default `"Systran/faster-whisper-large-v3"`).
- Language: `cfg.asr.language` (default `"en"`). v1 pins this; the
  spec does not support auto-detect.
- Beam size: `cfg.asr.beam_size` (default `5`).
- Compute type: `cfg.asr.compute_type` (default `"int8_float16"`).

## Model lifecycle

Two modes, controlled by `cfg.asr.mode` (default `"lazy"`; see
`07-configuration.md`):

| Mode     | When `WhisperModel` is constructed                                        |
|----------|---------------------------------------------------------------------------|
| `eager`  | At daemon startup (once). Blocks `stenographer run` for 5-30 s.          |
| `lazy`   | On the first hotkey press. The daemon boots in < 1 s; the first press     |
|          | plays the `model_loading` cue, shows a loading notification, and starts   |
|          | the recorder. The `WhisperModel` loads in a background thread (5-30 s),   |
|          | and when it finishes the `model_ready` cue and notification fire.         |
|          | Recording and transcription run in parallel with the load.                |

`asr.mode` applies only to the daemon (`stenographer run`). One-shot
commands (`transcribe FILE`, `dictate`) always construct the model
eagerly.

### `Model` (eager)

```python
from faster_whisper import WhisperModel

class Model:
    def __init__(self, cfg: AsrConfig) -> None:
        self._impl = WhisperModel(
            cfg.model,
            device="auto",          # CUDA if available, else CPU
            compute_type=cfg.compute_type,
        )

    def transcribe(self, samples: np.ndarray, language: str,
                   beam_size: int,
                   on_segment: Callable[[SegmentInfo], None] | None = None,
                   ) -> TranscriptionResult:
        """Run inference. Returns (text, duration, segments).

        If *on_segment* is not ``None`` it is called for each
        ``SegmentInfo`` as the model produces it, enabling the
        Session to stream partial transcripts before inference
        completes.
        """
        segments, info = self._impl.transcribe(
            samples,
            language=language,
            beam_size=beam_size,
            vad_filter=False,       # v1: trust the user's hotkey timing
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        return TranscriptionResult(
            text=text,
            duration_seconds=info.duration,
            segments=seg_infos,
        )
```

### `LazyModel` (lazy)

```python
import gc
import threading
from collections.abc import Callable

class LazyModel:
    """Wraps :class:`Model`, deferring construction to the first hotkey press.

    Used by the daemon when ``cfg.asr.mode == "lazy"``.  The session
    calls :meth:`ensure_loaded` (non-blocking) on the first hotkey
    press; the first :meth:`transcribe` call blocks until the inner
    :class:`Model` is constructed.

    Idle unload (``asr.idle_unload_seconds``)
    ------------------------------------------

    After ``asr.idle_unload_seconds`` (default 3600, i.e. 1 hour)
    without a :meth:`transcribe` call, the inner :class:`Model` is
    dropped and ``gc.collect()`` is called to reclaim GPU / CPU
    memory.  A subsequent :meth:`transcribe` or
    :meth:`ensure_loaded` triggers a fresh load with the full
    loading-sequence (``model_loading`` cue, notification, etc.).

    Set ``asr.idle_unload_seconds`` to 0 to disable unloading
    (the model stays resident once loaded).

    Threading of disposal
    ~~~~~~~~~~~~~~~~~~~~~

    The idle timer fires on its own thread but only enqueues an
    unload request onto the :class:`Worker`'s queue.  The actual
    disposal — ``del self._impl``, ``gc.collect()``, then
    ``malloc_trim(0)`` — runs on the **Worker thread**.  This is
    required because CTranslate2 binds the model to the worker
    thread via a ``thread_local`` replica slot; dropping the Python
    reference on a different thread frees the Python wrapper but
    defers the C++ destructor (and the ``munmap`` of the model
    weights) until the worker thread next becomes active or exits.
    Destroying the model on the worker thread lets the destructor
    run immediately, and ``malloc_trim(0)`` on the same thread
    returns the freed inference scratch to the OS at once.

    A *generation counter* guards against stale unload requests: a
    :meth:`transcribe` call that happens between the timer firing
    and the Worker dequeuing the request bumps the generation, and
    the Worker drops the stale request.
    """

    def __init__(
        self,
        cfg: AsrConfig,
        idle_unload_seconds: float | None = None,
    ) -> None: ...

    def attach_worker(self, worker: "Worker") -> None:
        """Stash a weakref to the owning Worker so the idle-unload timer
        can route disposal onto the Worker thread.  Called once by the
        CLI after both objects are constructed.
        """

    def ensure_loaded(
        self,
        on_loaded: Callable[[], None] | None = None,
    ) -> None:
        """Start loading the inner Model on a background thread.

        Idempotent: returns immediately if the model is already
        loaded or currently loading.  The optional *on_loaded*
        callback fires on the loader thread exactly once when the
        model becomes available.
        """

    def is_loaded(self) -> bool: ...

    def close(self) -> None:
        """Cancel the idle-unload timer.  Does NOT unload the model."""

    def transcribe(
        self, samples, language, beam_size, on_segment=None,
    ) -> TranscriptionResult:
        """Wait until the model is loaded (blocking), then run inference.

        Reschedules the idle-unload timer on every successful call.
        """

    def do_unload_on_worker(self, token: int) -> None:
        """Run on the Worker thread.  Drops the model iff *token* matches
        the current generation; otherwise no-ops (a transcribe happened
        since the request was enqueued).
        """
```

The :class:`Worker` gains a ``request_unload(token)`` method that
enqueues a sentinel onto its job queue; the Worker's run loop handles
it by calling ``model.do_unload_on_worker(token)`` and then
``malloc_trim(0)`` (Linux/glibc; no-op elsewhere).

On load failure the stored exception is re-raised from
:meth:`transcribe` so the Worker thread can route it through the
normal error path (``error`` cue, logged, resumable).

`faster-whisper` automatically downloads the model to the HuggingFace
Hub cache on first construction if it is not present. The startup
probe (`Capabilities.probe`, see `10-packaging.md`) checks for the
model **before** constructing `WhisperModel` so the daemon can exit
cleanly with a download hint rather than partially loading and
crashing.

## Threading

- A single `threading.Thread` ("worker thread") runs an event loop
  driven by a `queue.Queue` of `Job` objects.
- The Session submits a `Job(numpy.ndarray)` after the Recorder
  stops. The Worker calls `Model.transcribe`, optionally pushing
  partial `SegmentInfo` objects to a ``queue.Queue`` via the
  ``on_segment`` callback, and posts the final result back via a
  ``concurrent.futures.Future``.
- A sentinel `None` job causes the worker to exit cleanly.
- Only one inference runs at a time (the queue is unbounded, so
  bursty submissions are processed in order).

```python
@dataclass
class Job:
    samples: np.ndarray
    future: "concurrent.futures.Future[TranscriptionResult]"
    on_segment: Callable[[SegmentInfo], None] | None = None

@dataclass
class TranscriptionResult:
    text: str
    duration_seconds: float
    segments: list[SegmentInfo]
```

Using `Future` instead of a `Result` queue is acceptable; the spec
requires only that the Session can `submit` from any thread and
`await_result` with a timeout.

## Inference behavior

- `beam_size` is fixed per `cfg.asr.beam_size`. Not a per-utterance
  override.
- `vad_filter=False`. The hotkey defines utterance boundaries; the
  Worker does not introduce its own.
- `condition_on_previous_text=False`. Each utterance is independent.
- The output `text` is the concatenation of all segment texts, with
  no additional processing. **No auto-punctuation injection, no
  capitalization fix, no profanity filter** in v1.
- After inference completes, the Session checks each segment's
  `no_speech_prob`. If **every** segment has
  `no_speech_prob >= cfg.asr.silence_threshold` (default 0.6), the
  audio is treated as silence (the model hallucinated text on quiet
  audio). The Session logs at INFO, fires the `error` cue for user
  feedback, and skips injection + clipboard.
- If `text` is empty (faster-whisper returned no segments, or only
  whitespace), the Session logs at INFO, fires the `error` cue, and
  skips injection + clipboard.

### Streaming partial transcripts

When the Session calls ``Worker.submit(samples, on_segment=callback)``,
the Worker thread passes ``on_segment`` through to
``Model.transcribe()``.  As faster-whisper yields each segment the
callback fires on the Worker thread, which pushes the
``SegmentInfo`` into a ``queue.Queue`` polled by the Session.  The
Session calls ``Injector.type_text(seg.text, raw=True)`` for each
non-empty segment so that text arrives at the focused window as soon
as it is decoded, rather than waiting for the full utterance to
finish transcribing.

- Partial segments are injected *raw*: no strip, no truncation, no
  trailing-space append — the model's output passes through unchanged.
- When the final ``TranscriptionResult`` is ready, the Session
  compares the concatenated partial text against ``result.text`` and
  skips re-injection if they match (all partials already typed).
- The clipboard is populated with the final text only — never with
  intermediate partial text.

## Timing

- The Worker MUST return control to the Session as soon as inference
  completes.
- There is no hard latency target in v1. Empirically:
  - `large-v3` on CPU (8 cores, int8_float16): ~1-3x real time.
  - `large-v3` on a recent CUDA GPU: ~0.1-0.3x real time.
- For `transcribe FILE` mode, the CLI prints
  `transcribed <N> seconds of audio in <M> seconds` to stderr on
  success.

## Startup probe

`Capabilities.probe()` (see `10-packaging.md`) checks:

```python
from huggingface_hub import try_to_load_from_cache

result = try_to_load_from_cache(
    repo_id=cfg.asr.model,
    filename="config.json",  # every faster-whisper model has this
)
# result is a path string, a _CACHED_NO_EXIST sentinel, or None
ok = isinstance(result, str) and bool(result)
```

`has_asr_model` is `True` if and only if the model files are
present in the local cache. If `False`, the daemon prints the
`stenographer model download` hint and exits 78.

## `stenographer model download` subcommand

```python
# cli.py
def cmd_model_download(cfg: Config) -> int:
    """Download the configured ASR model and exit."""
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=cfg.asr.model)
    print(f"stenographer: downloaded {cfg.asr.model}")
    return 0
```

This is the only v1 way to fetch a model. There is no auto-download
on startup (per `09-error-handling.md`).

## Out of scope (v1)

- Auto language detection.
- Custom vocabulary / hotwords.
- Multiple models loaded simultaneously (per-language routing).
- GPU memory pre-allocation control.
- Quantization tuning beyond `compute_type`.

## Open questions

- Should we expose `vad_filter` as a config key for users on noisy
  microphones? v1: no.
- Should the Worker warm up the model with a 0.5 s silent buffer on
  startup so the first real inference is fast? v1: no.
