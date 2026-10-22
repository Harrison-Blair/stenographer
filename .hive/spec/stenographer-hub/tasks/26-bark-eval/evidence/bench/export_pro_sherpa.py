# SPDX-License-Identifier: GPL-3.0-or-later
"""Export Underdog Bark 3.0 Pro (transformers ParakeetForTDT) to sherpa-onnx's NeMo TDT layout.

Run in the scratch venv (torch, transformers>=5.19, onnx, onnxruntime):

    .scratch/venv/bin/python -I export_pro_sherpa.py \
        .scratch/models/bark-pro .scratch/models/bark-pro-sherpa

Writes encoder/decoder/joiner .onnx (fp32; encoder weights in encoder.weights), their int8
weight-only builds (*.int8.onnx, onnxruntime MatMulNBits, 8 bits, block 128, symmetric) and
tokens.txt. Graph inputs, outputs and encoder metadata follow k2-fsa's
scripts/nemo/parakeet-tdt-0.6b-v3/export_onnx.py, which sherpa-onnx's OfflineTransducerNeMoModel
reads. Then checks each fp32 and int8 graph against the PyTorch modules on random input.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from onnxruntime.quantization.matmul_nbits_quantizer import MatMulNBitsQuantizer
from torch import nn
from transformers import ParakeetForTDT

PRO_REPO = "ConwayResearch/Underdog-Bark-3.0-Pro"
PRO_REV = "4b5c51e04aa8d16dda9ecdff71bc29f7360149e4"


class Pointwise(nn.Module):
    """Kernel-1 Conv1d as the equivalent MatMul so the int8 quantizer covers it."""

    def __init__(self, conv: nn.Conv1d):
        super().__init__()
        self.weight = nn.Parameter(conv.weight.detach()[:, :, 0].clone(), requires_grad=False)
        self.bias = None if conv.bias is None else nn.Parameter(conv.bias.detach().clone())

    def forward(self, x):
        return nn.functional.linear(x.transpose(1, 2), self.weight, self.bias).transpose(1, 2)


class Encoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.m = model

    def forward(self, audio_signal, length):  # (N, 128, T) f32, (N,) i64
        x = audio_signal.transpose(1, 2)
        mask = (torch.arange(x.shape[1])[None, :] < length[:, None]).long()
        h = self.m.encoder(input_features=x, attention_mask=mask).last_hidden_state
        lens = self.m._get_subsampling_output_length(length).to(torch.int64)
        return h.transpose(1, 2), lens


class Decoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.d = model.decoder

    def forward(self, targets, target_length, h, c):
        out, (h2, c2) = self.d.lstm(self.d.embedding(targets.to(torch.int64)), (h, c))
        return self.d.decoder_projector(out).transpose(1, 2), target_length, h2, c2


class Joiner(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.proj = model.encoder_projector
        self.joint = model.joint

    def forward(self, encoder_outputs, decoder_outputs):  # (N, 1024, T), (N, 640, U)
        f = self.proj(encoder_outputs.transpose(1, 2))
        g = decoder_outputs.transpose(1, 2)
        return self.joint.head(self.joint.activation(f[:, :, None, :] + g[:, None, :, :]))


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    torch.set_num_threads(8)

    model = ParakeetForTDT.from_pretrained(src, dtype=torch.float32, local_files_only=True).eval()
    model.config._attn_implementation = "eager"
    model.encoder.config._attn_implementation = "eager"
    for layer in model.encoder.layers:
        for name in ("pointwise_conv1", "pointwise_conv2"):
            setattr(layer.conv, name, Pointwise(getattr(layer.conv, name)))
    enc, dec, joi = Encoder(model).eval(), Decoder(model).eval(), Joiner(model).eval()
    blank = model.config.blank_token_id
    layers, hidden = model.config.num_decoder_layers, model.config.decoder_hidden_size

    with torch.no_grad():
        frames = 501
        torch.onnx.export(
            enc,
            (torch.randn(1, 128, frames), torch.tensor([frames])),
            str(tmp / "encoder.onnx"),
            dynamo=False,
            opset_version=17,
            input_names=["audio_signal", "length"],
            output_names=["outputs", "encoded_lengths"],
            dynamic_axes={
                "audio_signal": {0: "N", 2: "T"},
                "length": {0: "N"},
                "outputs": {0: "N", 2: "T_out"},
                "encoded_lengths": {0: "N"},
            },
        )
        h0 = torch.zeros(layers, 1, hidden)
        torch.onnx.export(
            dec,
            (
                torch.tensor([[blank]], dtype=torch.int32),
                torch.tensor([1], dtype=torch.int32),
                h0,
                h0,
            ),
            str(tmp / "decoder.onnx"),
            dynamo=False,
            opset_version=17,
            input_names=["targets", "target_length", "states.1", "states.2"],
            output_names=["outputs", "prednet_lengths", "states", "states.2_out"],
            dynamic_axes={
                "targets": {0: "N", 1: "U"},
                "target_length": {0: "N"},
                "states.1": {1: "N"},
                "states.2": {1: "N"},
                "outputs": {0: "N", 2: "U"},
                "prednet_lengths": {0: "N"},
                "states": {1: "N"},
                "states.2_out": {1: "N"},
            },
        )
        torch.onnx.export(
            joi,
            (torch.randn(1, 1024, 1), torch.randn(1, hidden, 1)),
            str(tmp / "joiner.onnx"),
            dynamo=False,
            opset_version=17,
            input_names=["encoder_outputs", "decoder_outputs"],
            output_names=["outputs"],
            dynamic_axes={
                "encoder_outputs": {0: "N", 2: "T"},
                "decoder_outputs": {0: "N", 2: "U"},
                "outputs": {0: "N", 1: "T", 2: "U"},
            },
        )

    meta = {
        "vocab_size": str(blank),  # NeMo convention: without the blank
        "normalize_type": "per_feature",
        "pred_rnn_layers": str(layers),
        "pred_hidden": str(hidden),
        "subsampling_factor": "8",
        "model_type": "EncDecRNNTBPEModel",
        "version": "2",
        "model_author": "Conway Research (Underdog Bark 3.0 Pro); NVIDIA (parakeet-tdt-0.6b-v3)",
        # sherpa-onnx enables TDT decoding when `url` contains "tdt".
        "url": f"https://huggingface.co/{PRO_REPO}#parakeet-tdt-0.6b-v3",
        "comment": f"{PRO_REPO}@{PRO_REV}, CC-BY-4.0; local export for evaluation only",
        "feat_dim": "128",
        "license": "CC-BY-4.0",
    }
    for name in ("encoder", "decoder", "joiner"):
        m = onnx.load(str(tmp / f"{name}.onnx"))
        if name == "encoder":
            del m.metadata_props[:]
            for k, v in meta.items():
                p = m.metadata_props.add()
                p.key, p.value = k, v
            onnx.save(
                m,
                str(out / "encoder.onnx"),
                save_as_external_data=True,
                all_tensors_to_one_file=True,
                location="encoder.weights",
                size_threshold=0,
            )
        else:
            onnx.save(m, str(out / f"{name}.onnx"))
        # Saving with external data rewrites `m` in place; reload with absolute weight paths.
        m = onnx.load(str(out / f"{name}.onnx"))
        q = MatMulNBitsQuantizer(m, bits=8, block_size=128, is_symmetric=True, accuracy_level=4)
        q.process()
        onnx.save(q.model.model, str(out / f"{name}.int8.onnx"))
        del m, q
    shutil.rmtree(tmp)

    tok = json.loads((src / "tokenizer.json").read_text())["model"]["vocab"]
    vocab = (
        [t for t, _ in sorted(tok.items(), key=lambda kv: kv[1])]
        if isinstance(tok, dict)
        else [t[0] for t in tok]
    )
    assert len(vocab) == blank and not any(" " in t or not t for t in vocab)
    with open(out / "tokens.txt", "w", encoding="utf-8") as f:
        f.writelines(f"{t} {i}\n" for i, t in enumerate(vocab))
        f.write(f"<blk> {blank}\n")

    # Graph check: ONNX against PyTorch on the same random input.
    rng = np.random.default_rng(0)
    x = rng.standard_normal((1, 128, 300), dtype=np.float32)
    ln = np.array([300], np.int64)
    tgt = np.array([[17]], np.int32)
    st = rng.standard_normal((layers, 1, hidden), dtype=np.float32)
    with torch.no_grad():
        ref_e = enc(torch.from_numpy(x), torch.from_numpy(ln))[0].numpy()
        ref_d = dec(
            torch.from_numpy(tgt),
            torch.tensor([1], dtype=torch.int32),
            torch.from_numpy(st),
            torch.from_numpy(st),
        )[0].numpy()
        ref_j = joi(torch.from_numpy(ref_e[:, :, :5]), torch.from_numpy(ref_d))[0].numpy()
    for suffix in ("", ".int8"):
        so = ort.SessionOptions()
        so.intra_op_num_threads = 8
        e = ort.InferenceSession(str(out / f"encoder{suffix}.onnx"), so).run(
            None, {"audio_signal": x, "length": ln}
        )[0]
        d = ort.InferenceSession(str(out / f"decoder{suffix}.onnx"), so).run(
            None,
            {
                "targets": tgt,
                "target_length": np.array([1], np.int32),
                "states.1": st,
                "states.2": st,
            },
        )[0]
        j = ort.InferenceSession(str(out / f"joiner{suffix}.onnx"), so).run(
            None, {"encoder_outputs": ref_e[:, :, :5], "decoder_outputs": ref_d}
        )[0]
        for name, a, b in (("encoder", e, ref_e), ("decoder", d, ref_d), ("joiner", j, ref_j)):
            rel = float(np.abs(a - b).max() / (np.abs(b).max() + 1e-9))
            same_arg = (
                float((a.argmax(-1) == b.argmax(-1)).mean()) if name == "joiner" else float("nan")
            )
            print(
                f"check {name}{suffix or '.fp32'}: max rel diff {rel:.2e} "
                f"joiner argmax agreement {same_arg}"
            )
    for f in sorted(out.iterdir()):
        print(f"file {f.name} {f.stat().st_size}")


if __name__ == "__main__":
    main()
