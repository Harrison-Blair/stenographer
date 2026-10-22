# SPDX-License-Identifier: GPL-3.0-or-later
"""Bark 3.0 Pro or Clean through transformers ParakeetForTDT (scratch venv).

    .scratch/venv/bin/python -I run_hf.py pro|clean cpu|cuda OUT.json

Pro: model.safetensors, evaluated with 0.25 s of leading silence (model card).
Clean: model.bark unpacked with Conway Research's bark_loader.load_state_dict (authorised repo,
read before use: numpy/lzma/constriction, no network), no padding (model card). The loader's own
load_model/transcribe fetch nvidia/parakeet-tdt-0.6b-v3 configs from the Hub, so this runner uses
the Pro repo's processor and generation config instead (same tokenizer and feature extractor;
Clean's embedded config equals Pro's config.json apart from dtype).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch
from common import WORKTREE, run, words_from_pieces

MODELS = WORKTREE / ".scratch/models"


def main() -> None:
    which, device, out = sys.argv[1], sys.argv[2], sys.argv[3]
    torch.set_num_threads(8)
    pad_s = 0.25 if which == "pro" else 0.0
    # Pro on GPU in BF16 as its card runs it; everything else FP32 (the loaders' defaults).
    dtype = torch.bfloat16 if (which == "pro" and device == "cuda") else torch.float32
    sync = torch.cuda.synchronize if device == "cuda" else (lambda: None)

    def load():
        from transformers import AutoProcessor, GenerationConfig, ParakeetForTDT, ParakeetTDTConfig

        pro = MODELS / "bark-pro"
        proc = AutoProcessor.from_pretrained(pro, local_files_only=True)
        if which == "pro":
            model = ParakeetForTDT.from_pretrained(pro, dtype=dtype, local_files_only=True)
        else:
            spec = importlib.util.spec_from_file_location(
                "bark_loader", MODELS / "bark-clean/bark_loader.py"
            )
            loader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loader)
            sd, cfg = loader.load_state_dict(str(MODELS / "bark-clean/model.bark"))
            model = ParakeetForTDT(ParakeetTDTConfig.from_dict(cfg))
            missing, unexpected = model.load_state_dict(
                {k: v.float() for k, v in sd.items()}, strict=False
            )
            assert not unexpected and all("num_batches_tracked" in m for m in missing)
            model.generation_config = GenerationConfig.from_pretrained(pro, local_files_only=True)
        model = model.to(device=device, dtype=dtype).eval()

        def decode(samples):
            wave = np.concatenate(
                [np.zeros(int(pad_s * 16000), np.float32), samples.astype(np.float32)]
            )
            inputs = proc(wave, sampling_rate=16000, return_tensors="pt")
            inputs = {
                k: (v.to(device, dtype) if v.dtype.is_floating_point else v.to(device))
                for k, v in inputs.items()
            }
            with torch.inference_mode():
                g = model.generate(**inputs, return_dict_in_generate=True)
            texts, stamps = proc.decode(
                g.sequences, durations=g.durations, skip_special_tokens=True
            )
            pieces = [(t["token"], t["start"] - pad_s, t["end"] - pad_s) for t in stamps[0]]
            return texts[0].strip(), words_from_pieces(pieces)

        return decode

    meta = {
        "model": which,
        "runtime": "transformers",
        "device": device,
        "dtype": str(dtype),
        "pad_s": pad_s,
        "threads": 8,
        "torch": torch.__version__,
        "transformers": __import__("transformers").__version__,
    }
    run(f"{which}-hf-{device}", load, out, meta, sync)


if __name__ == "__main__":
    main()
