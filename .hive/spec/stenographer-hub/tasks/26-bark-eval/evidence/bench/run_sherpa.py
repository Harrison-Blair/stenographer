# SPDX-License-Identifier: GPL-3.0-or-later
"""A Bark NeMo-TDT int8 export through sherpa-onnx (stenographer's .venv: sherpa-onnx 1.13.8, CPU).

    .venv/bin/python -I run_sherpa.py LABEL MODEL_DIR PAD_S OUT.json

Loads only encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx and tokens.txt from MODEL_DIR.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import sherpa_onnx
from common import run, words_from_pieces


def main() -> None:
    label, model_dir, pad_s, out = sys.argv[1], Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4]

    def load():
        rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            model_type="nemo_transducer",
            num_threads=8,
            provider="cpu",
        )

        def decode(samples):
            s = rec.create_stream()
            s.accept_waveform(
                16000, np.concatenate([np.zeros(int(pad_s * 16000), np.float32), samples])
            )
            rec.decode_stream(s)
            r = s.result
            durs = list(r.durations) or [0.0] * len(r.tokens)
            pieces = [
                (tok, ts - pad_s, ts - pad_s + d)
                for tok, ts, d in zip(r.tokens, r.timestamps, durs, strict=True)
                if tok != "<unk>"
            ]
            return r.text.replace("<unk>", "").strip(), words_from_pieces(pieces)

        return decode

    meta = {
        "model": label.split("-")[0],
        "runtime": "sherpa-onnx int8",
        "device": "cpu",
        "pad_s": pad_s,
        "threads": 8,
        "sherpa_onnx": sherpa_onnx.__version__,
        "model_dir": str(model_dir),
    }
    run(label, load, out, meta)


if __name__ == "__main__":
    main()
