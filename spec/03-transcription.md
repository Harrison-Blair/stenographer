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
                   ) -> tuple[str, list[SegmentInfo]]:
        """Run inference. Returns (text, segments).

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
        return text, list(segments)
```

The `WhisperModel` is constructed **once** at daemon startup. Loading
`large-v3` takes 5-30 s; this is acceptable for the daemon (one-time
cost) but `transcribe FILE` must show a progress hint.

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
- If `text` is empty (faster-whisper returned no segments, or only
  whitespace), the Session logs at INFO level
  (`asr: no speech recognized for utterance`) and skips injection +
  clipboard. **No `error` cue is fired** — silence is not an error.

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
