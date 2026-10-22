# SPDX-License-Identifier: GPL-3.0-or-later
"""The current stenographer ASR path: lib.transcribe.model.Model with the default AsrConfig.

    .venv/bin/python -I run_whisper.py cpu|cuda MODEL_DIR OUT.json

Model() uses device="auto"; the cpu run hides the GPU with CUDA_VISIBLE_DEVICES="" before import.
MODEL_DIR is a local CTranslate2 large-v3-turbo snapshot (the default
deepdml/faster-whisper-large-v3-turbo-ct2 is not downloaded on this machine; the user's configured
dropbox-dash/faster-whisper-large-v3-turbo is used instead).
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

device = sys.argv[1]
if device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import WORKTREE, run  # noqa: E402

sys.path.insert(0, str(WORKTREE / "src"))

import ctranslate2  # noqa: E402
import faster_whisper  # noqa: E402

from stenographer.lib.config.models import Config  # noqa: E402
from stenographer.lib.transcribe.model import Model  # noqa: E402


def main() -> None:
    model_dir, out = sys.argv[2], sys.argv[3]
    cfg = replace(Config.defaults().asr, model=model_dir)

    def load():
        model = Model(cfg)

        def decode(samples):
            r = model.transcribe(samples)
            words = [
                (round(w.start, 3), round(w.end, 3), w.word.strip())
                for s in r.segments
                for w in s.words
            ]
            return r.text.strip(), words

        return decode

    meta = {
        "model": "turbo",
        "runtime": "faster-whisper (stenographer Model)",
        "device": device,
        "compute_type": cfg.compute_type,
        "beam_size": cfg.beam_size,
        "vad_filter": cfg.vad_filter,
        "faster_whisper": faster_whisper.__version__,
        "ctranslate2": ctranslate2.__version__,
        "model_dir": model_dir,
    }
    run(f"turbo-ct2-{device}", load, out, meta)


if __name__ == "__main__":
    main()
