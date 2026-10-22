# SPDX-License-Identifier: GPL-3.0-or-later
"""Task 44 evidence: real Bark Pro decodes through Model.transcribe and the dictation path.

Usage: python bark_evidence.py CLIP.wav REFERENCE.txt WORKTREE
The clip and reference are read in place and never written.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import time

import numpy as np
import soundfile as sf

from stenographer.lib.audio.constants import SAMPLE_RATE
from stenographer.lib.audio.resample import _resample_poly
from stenographer.lib.config.models import Config
from stenographer.lib.contracts.overlay_state import OverlayState
from stenographer.lib.daemon.pipeline import UtterancePipeline
from stenographer.lib.daemon.telemetry import UtteranceTelemetry
from stenographer.lib.platform import current_platform
from stenographer.lib.transcribe import bark_download
from stenographer.lib.transcribe.dictation_vad import dictation_speech
from stenographer.lib.transcribe.model import Model


def rss_mib() -> tuple[float, float]:
    fields = {}
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        fields[key] = value
    return (int(fields["VmRSS"].split()[0]) / 1024, int(fields["VmHWM"].split()[0]) / 1024)


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1] / len(ref)


class CountingWorker:
    """The daemon's worker seam over the real in-process Model; counts decode calls."""

    is_model_ready = True
    last_timings = None

    def __init__(self, model: Model) -> None:
        self.model = model
        self.calls = 0
        self.decode_s: list[float] = []

    def transcribe(self, samples, utterance=None):
        self.calls += 1
        started = time.perf_counter()
        result = self.model.transcribe(samples)
        self.decode_s.append(time.perf_counter() - started)
        return result


class RecordingDeliverer:
    last_timings = None

    def __init__(self) -> None:
        self.delivered: list[str] = []

    def deliver(self, text, *, original=None, on_copied=None, cancelled=None) -> bool:
        self.delivered.append(text)
        return True

    def restore_clipboard(self) -> bool:
        return True


def pipeline(worker, deliverer, vad_path, *, min_speech_rms):
    return UtterancePipeline(
        min_speech_rms=min_speech_rms,
        worker=worker,
        deliverer=deliverer,
        telemetry=UtteranceTelemetry(),
        publish_state=lambda _state: None,
        fail=lambda message: print(f"FAIL: {message}"),
        play_cue=lambda _name: None,
        cancelled=lambda: False,
        cancel_state=lambda: OverlayState.CANCELLED,
        speech_filter=lambda samples: dictation_speech(samples, vad_path),
    )


def main() -> None:
    clip, reference_path, worktree = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
    data_dir = current_platform().data_dir(os.environ, pathlib.Path.home())
    assert data_dir.is_relative_to(worktree), f"data dir outside the worktree: {data_dir}"
    vad_path = data_dir / "models" / "live" / "silero_vad.onnx"
    print(f"data_dir: {data_dir}")
    print(f"bark model cached: {bark_download.is_model_cached(data_dir)}")
    print(f"vad model present: {vad_path.is_file()}")

    audio, rate = sf.read(clip, dtype="float32", always_2d=True)
    mono = np.ascontiguousarray(audio[:, 0])
    if rate != SAMPLE_RATE:
        mono = _resample_poly(mono, rate, SAMPLE_RATE)
    reference = pathlib.Path(reference_path).read_text(encoding="utf-8").strip()
    print(f"clip: {pathlib.Path(clip).name} rate={rate} seconds={mono.size / SAMPLE_RATE:.2f}")
    print(f"rss before load: {rss_mib()[0]:.0f} MiB")

    cfg = Config.defaults().asr
    started = time.perf_counter()
    model = Model(cfg)
    print(f"model load: {time.perf_counter() - started:.2f} s cpu_threads={model.cpu_threads}")
    print(f"rss after load: {rss_mib()[0]:.0f} MiB")

    print("\n== 1. Model.transcribe on the whole clip")
    started = time.perf_counter()
    direct = model.transcribe(mono)
    elapsed = time.perf_counter() - started
    [segment] = direct.segments
    print(f"decode: {elapsed:.2f} s (RTF {elapsed / (mono.size / SAMPLE_RATE):.3f})")
    print(f"text: {direct.text}")
    print(f"reference: {reference}")
    print(f"WER vs reference: {wer(reference, direct.text):.3f}")
    print(f"segments={len(direct.segments)} words={len(segment.words)}")
    first, last = segment.words[0], segment.words[-1]
    print(f"first word {first.word!r} {first.start:.2f}-{first.end:.2f} p={first.probability:.3f}")
    print(f"last word {last.word!r} {last.start:.2f}-{last.end:.2f} p={last.probability:.3f}")
    rss, peak = rss_mib()
    print(f"rss after decode: {rss:.0f} MiB (peak {peak:.0f} MiB)")

    print("\n== 2. Dictation path: UtterancePipeline (gate, VAD, decode, format, deliver)")
    worker, deliverer = CountingWorker(model), RecordingDeliverer()
    started = time.perf_counter()
    outcome = pipeline(
        worker, deliverer, vad_path, min_speech_rms=Config.defaults().audio.min_speech_rms
    ).run(mono, utterance=1, record=None)
    total = time.perf_counter() - started
    speech = dictation_speech(mono, vad_path)
    print(f"outcome: {outcome} decode_calls={worker.calls}")
    print(f"vad kept: {speech.size / SAMPLE_RATE:.2f} s of {mono.size / SAMPLE_RATE:.2f} s")
    print(f"decode: {worker.decode_s[0]:.2f} s; whole pipeline: {total:.2f} s")
    print(f"delivered: {deliverer.delivered[0]}")
    print(f"WER vs reference: {wer(reference, deliverer.delivered[0]):.3f}")
    rss, peak = rss_mib()
    print(f"rss after dictation: {rss:.0f} MiB (peak {peak:.0f} MiB)")

    print("\n== 3. Two seconds of digital silence")
    silence = np.zeros(2 * SAMPLE_RATE, dtype=np.float32)
    kept = dictation_speech(silence, vad_path)
    print(f"dictation VAD kept frames: {kept.size}")
    for label, gate in (("stock gate", Config.defaults().audio.min_speech_rms), ("gate 0", 0.0)):
        worker, deliverer = CountingWorker(model), RecordingDeliverer()
        outcome = pipeline(worker, deliverer, vad_path, min_speech_rms=gate).run(
            silence, utterance=2, record=None
        )
        print(
            f"{label} (min_speech_rms={gate}): outcome={outcome} "
            f"decode_calls={worker.calls} delivered={deliverer.delivered}"
        )
    model.close()


if __name__ == "__main__":
    main()
