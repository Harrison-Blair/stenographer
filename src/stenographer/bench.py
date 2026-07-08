# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline benchmark harness for transcription latency/quality exploration.

Compares batch ASR configs (model x beam x compute_type) for cold-load time,
real-time factor, and word-error-rate against a gold reference, and simulates
the streaming (LocalAgreement) path for intra-utterance latency. Invoked via
``stenographer bench`` (see ``cli.cmd_bench``); heavy imports live here so the
argument parser stays light.
"""

from __future__ import annotations

import dataclasses
import pathlib
import time
from dataclasses import dataclass

import numpy as np

from stenographer.asr.model import Model
from stenographer.asr.streaming import StreamingTranscriber
from stenographer.config import Config

_GOLD_MODEL = "Systran/faster-whisper-large-v3"
_GOLD_BEAM = 5
_GOLD_COMPUTE = "int8"

# Punctuation stripped when tokenising for WER (matches streaming._norm intent).
_PUNCT = ".,!?;:\"'“”‘’…-"  # noqa: RUF001

_UNITS = {
    "zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"point"}


def _chunks_to_str(chunks: list[int]) -> str:
    """Render parsed cardinal chunks, applying year / digit-sequence heuristics.

    Spoken numbers are ambiguous: "twenty twenty six" is the year 2026, while
    "one two three" is the digit string 123. These heuristics collapse the
    common dictation cases so they match their digit spellings.
    """
    if len(chunks) == 2 and all(10 <= c <= 99 for c in chunks):
        return str(chunks[0] * 100 + chunks[1])  # year: "nineteen eighty four"
    if len(chunks) >= 2 and all(0 <= c <= 9 for c in chunks):
        return "".join(str(c) for c in chunks)  # digit sequence: "one two three"
    return " ".join(str(c) for c in chunks)


def _parse_cardinal(words: list[str]) -> str:
    """Convert a run of number-words to canonical digit token(s)."""
    if "point" in words:  # decimal: integer part . spoken digits
        i = words.index("point")
        whole = _parse_cardinal(words[:i]) or "0"
        frac = "".join(str(_UNITS.get(w, "")) for w in words[i + 1 :])
        return f"{whole}.{frac}" if frac else whole
    if any(w in _SCALES for w in words):  # scale-based cardinal: one value
        total = 0
        cur = 0
        for w in words:
            if w in _UNITS:
                cur += _UNITS[w]
            elif w in _TENS:
                cur += _TENS[w]
            elif w == "hundred":
                cur = (cur or 1) * 100
            else:  # thousand / million
                total += (cur or 1) * _SCALES[w]
                cur = 0
        return str(total + cur)
    # No scales: split into ten(+unit) / teen / unit chunks.
    chunks: list[int] = []
    i = 0
    while i < len(words):
        if words[i] in _TENS:
            val = _TENS[words[i]]
            if i + 1 < len(words) and words[i + 1] in _UNITS and _UNITS[words[i + 1]] < 10:
                val += _UNITS[words[i + 1]]
                i += 1
            chunks.append(val)
        else:
            chunks.append(_UNITS[words[i]])
        i += 1
    return _chunks_to_str(chunks)


def _normalize_numbers(words: list[str]) -> list[str]:
    """Replace maximal runs of number-words with their digit spelling."""
    out: list[str] = []
    i = 0
    while i < len(words):
        if words[i] in _NUMBER_WORDS:
            j = i
            while j < len(words) and words[j] in _NUMBER_WORDS:
                j += 1
            run = words[i:j]
            # Drop leading/trailing bare "point" (only meaningful between digits).
            while run and run[-1] == "point":
                run = run[:-1]
            while run and run[0] == "point":
                run = run[1:]
            if run:
                out.append(_parse_cardinal(run))
            i = j
        else:
            out.append(words[i])
            i += 1
    return out


def _norm_words(text: str) -> list[str]:
    raw = [t for t in (w.strip(_PUNCT).lower().replace(",", "") for w in text.split()) if t]
    return _normalize_numbers(raw)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word-level Levenshtein error rate of *hypothesis* against *reference*.

    Returns edits / max(len(reference_words), 1). 0.0 == identical.
    """
    ref = _norm_words(reference)
    hyp = _norm_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    # Levenshtein over word tokens, O(len(ref)) rolling rows.
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cost = 0 if r == h else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(hyp)] / len(ref)


@dataclass
class Clip:
    name: str
    samples: np.ndarray  # (N, 1) float32
    duration: float


@dataclass
class BatchRow:
    model: str
    beam: int
    compute: str
    load_s: float
    rtf: float
    wer: float | None  # None for the gold row
    is_gold: bool
    text: str


@dataclass
class StreamRow:
    model: str
    chunk: float
    agree: int
    context: bool
    first_commit_s: float | None
    avg_commit_lag_s: float | None
    revisions: int
    final_wer: float


def _short_model(model: str) -> str:
    return model.rsplit("/", 1)[-1].replace("faster-", "").replace("whisper-", "")


# -- audio input ------------------------------------------------------------


def load_clips(paths: list[pathlib.Path], sample_rate: int) -> list[Clip]:
    import soundfile

    clips: list[Clip] = []
    for path in paths:
        samples, sr = soundfile.read(str(path), dtype="float32", always_2d=True)
        samples = samples[:, 0:1]
        if sr != sample_rate:
            from stenographer.audio.capture import _resample_poly

            samples = _resample_poly(samples[:, 0], sr, sample_rate).reshape(-1, 1)
        clips.append(Clip(name=path.name, samples=samples, duration=samples.shape[0] / sample_rate))
    return clips


def record_clip(cfg: Config, seconds: float, save: pathlib.Path | None) -> Clip:
    from stenographer.audio.capture import Recorder

    errors: list[Exception] = []
    rec = Recorder(
        sample_rate=cfg.audio.sample_rate,
        frames_per_buffer=cfg.audio.frames_per_buffer,
        device=cfg.audio.input_device,
        on_error=errors.append,
    )
    print("bench: starting in 3…", flush=True)
    time.sleep(1)
    print("bench: 2…", flush=True)
    time.sleep(1)
    print("bench: 1…", flush=True)
    time.sleep(1)
    print(f"bench: 🎙  RECORDING {seconds:g}s — speak now!", flush=True)
    rec.start()
    time.sleep(seconds)
    samples = rec.stop()
    print("bench: recording stopped.", flush=True)
    if errors:
        print(f"bench: capture warning: {errors[0]}", flush=True)
    if save is not None:
        import soundfile

        soundfile.write(str(save), samples, cfg.audio.sample_rate)
        print(f"bench: saved recording to {save}", flush=True)
    return Clip(
        name="<mic>", samples=samples, duration=samples.shape[0] / cfg.audio.sample_rate
    )


# -- batch matrix -----------------------------------------------------------


def run_batch(
    cfg: Config,
    clips: list[Clip],
    models: list[str],
    beams: list[int],
    computes: list[str],
) -> tuple[list[BatchRow], str]:
    """Run every (model, compute) x beam combo over all clips.

    Models are loaded once per (model, compute) pair; beams reuse the loaded
    model. Cold-load time is measured per pair and attributed to each of its
    beam rows.
    """
    total_audio = sum(c.duration for c in clips)
    # Ensure the gold config is present so WER always has a reference.
    pairs: list[tuple[str, str]] = []
    for m in models:
        for ct in computes:
            pairs.append((m, ct))
    if (_GOLD_MODEL, _GOLD_COMPUTE) not in pairs:
        pairs.insert(0, (_GOLD_MODEL, _GOLD_COMPUTE))
    beam_set = list(beams)
    if _GOLD_MODEL in {p[0] for p in pairs} and _GOLD_BEAM not in beam_set:
        beam_set = [*beam_set, _GOLD_BEAM]

    rows: list[BatchRow] = []
    gold_text = ""
    for model_id, compute in pairs:
        asr_cfg = dataclasses.replace(cfg.asr, model=model_id, compute_type=compute)
        print(f"bench: loading {_short_model(model_id)} ({compute})…")
        t0 = time.monotonic()
        try:
            model = Model(asr_cfg)
        except Exception as exc:
            print(f"bench: SKIP {_short_model(model_id)} ({compute}): {exc}")
            continue
        load_s = time.monotonic() - t0
        try:
            for beam in beam_set:
                infer_s = 0.0
                parts: list[str] = []
                for clip in clips:
                    t = time.monotonic()
                    result = model.transcribe(clip.samples, cfg.asr.language, beam)
                    infer_s += time.monotonic() - t
                    parts.append(result.text)
                text = " ".join(parts).strip()
                rtf = infer_s / total_audio if total_audio > 0 else 0.0
                is_gold = (
                    model_id == _GOLD_MODEL and beam == _GOLD_BEAM and compute == _GOLD_COMPUTE
                )
                if is_gold:
                    gold_text = text
                rows.append(
                    BatchRow(
                        model=model_id,
                        beam=beam,
                        compute=compute,
                        load_s=load_s,
                        rtf=rtf,
                        wer=None,
                        is_gold=is_gold,
                        text=text,
                    )
                )
        finally:
            model.close()

    for row in rows:
        if not row.is_gold:
            row.wer = word_error_rate(gold_text, row.text)
    return rows, gold_text


# -- streaming simulation ---------------------------------------------------


def run_streaming(
    cfg: Config,
    clips: list[Clip],
    model_id: str,
    chunk: float,
    agree: int,
    use_context: bool,
    gold_text: str,
) -> StreamRow:
    """Feed clips through the streaming transcriber in chunk-sized steps."""
    asr_cfg = dataclasses.replace(cfg.asr, model=model_id)
    print(f"bench: streaming sim with {_short_model(model_id)} (chunk={chunk}s agree={agree})…")
    model = Model(asr_cfg)
    sr = cfg.audio.sample_rate
    step = max(1, round(chunk * sr))
    first_commit: float | None = None
    lags: list[float] = []
    revisions = 0
    parts: list[str] = []
    try:
        for clip in clips:
            st = StreamingTranscriber(model, sample_rate=sr, agree=agree, use_context=use_context)
            mono = clip.samples[:, 0]
            for start in range(0, mono.shape[0], step):
                res = st.push(mono[start : start + step])
                now = min((start + step) / sr, clip.duration)
                if res.newly_committed and first_commit is None:
                    first_commit = now
                for end_t in res.committed_audio_ends:
                    lags.append(max(0.0, now - end_t))
                if res.revised and res.provisional:
                    revisions += 1
            parts.append(st.finish())
    finally:
        model.close()
    final_text = " ".join(parts).strip()
    return StreamRow(
        model=model_id,
        chunk=chunk,
        agree=agree,
        context=use_context,
        first_commit_s=first_commit,
        avg_commit_lag_s=(sum(lags) / len(lags)) if lags else None,
        revisions=revisions,
        final_wer=word_error_rate(gold_text, final_text),
    )


# -- reporting --------------------------------------------------------------


def _fmt(v: float | None, spec: str) -> str:
    return "  -  " if v is None else format(v, spec)


def print_batch(rows: list[BatchRow]) -> None:
    print("\nBATCH:")
    print(f" {'model':<20} {'beam':>4}  {'compute':<13} {'load(s)':>7} {'RTF':>6} {'WER':>8}")
    for r in rows:
        wer = "(gold)" if r.is_gold else _fmt(r.wer, ".1%")
        print(
            f" {_short_model(r.model):<20} {r.beam:>4}  {r.compute:<13} "
            f"{r.load_s:>7.1f} {r.rtf:>5.2f}x {wer:>8}"
        )


def print_streaming(row: StreamRow) -> None:
    print(
        f"\nSTREAMING ({_short_model(row.model)}, chunk={row.chunk:g}s, "
        f"agree={row.agree}, context={'on' if row.context else 'off'}):"
    )
    print(f" first-commit:   {_fmt(row.first_commit_s, '.2f')} s")
    print(f" avg-commit-lag: {_fmt(row.avg_commit_lag_s, '.2f')} s")
    print(f" revisions:      {row.revisions}")
    print(f" final-WER-vs-batch-gold: {row.final_wer:.1%}")


# -- entry point ------------------------------------------------------------


def run(
    cfg: Config,
    *,
    files: list[pathlib.Path],
    record_seconds: float | None,
    save: pathlib.Path | None,
    models: list[str],
    beams: list[int],
    computes: list[str],
    streaming: bool,
    chunk: float,
    agree: int,
    context: bool,
    show_text: bool = False,
    stream_model: str | None = None,
) -> int:
    if record_seconds is not None:
        clips = [record_clip(cfg, record_seconds, save)]
    else:
        clips = load_clips(files, cfg.audio.sample_rate)
    if not clips or all(c.samples.shape[0] == 0 for c in clips):
        print("bench: no audio captured/loaded")
        return 2
    total = sum(c.duration for c in clips)
    print(f"bench: {len(clips)} clip(s), {total:.1f}s total audio")

    rows, gold_text = run_batch(cfg, clips, models, beams, computes)
    print_batch(rows)

    if show_text:
        print("\nTRANSCRIPTS:")
        for r in rows:
            tag = " (gold)" if r.is_gold else ""
            print(f"\n [{_short_model(r.model)} beam={r.beam} {r.compute}{tag}]")
            print(f"   {r.text or '<empty>'}")

    if streaming:
        row = run_streaming(
            cfg, clips, stream_model or _GOLD_MODEL, chunk, agree, context, gold_text
        )
        print_streaming(row)
    return 0
