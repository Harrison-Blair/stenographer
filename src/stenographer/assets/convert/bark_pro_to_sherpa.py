# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert Underdog Bark 3.0 Pro (transformers ParakeetForTDT) to sherpa-onnx int8 files.

``stenographer model download --asr`` runs this script in a temporary venv that holds
only the pinned packages:

    <venv>/bin/python -I bark_pro_to_sherpa.py INPUT_DIR OUTPUT_DIR

INPUT_DIR holds the downloaded source files. OUTPUT_DIR must be an empty directory. The
script writes only encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx and tokens.txt
there. It keeps the fp32 intermediates in OUTPUT_DIR/.tmp and deletes them before it exits.
Graph inputs, outputs and encoder metadata follow k2-fsa's
scripts/nemo/parakeet-tdt-0.6b-v3/export_onnx.py, which sherpa-onnx's
OfflineTransducerNeMoModel reads. The int8 builds are onnxruntime MatMulNBits, 8 bits,
block 128, symmetric (weight-only). Seeds and thread counts are fixed so that two runs
give the same bytes.

The script imports only the standard library and the pinned packages, never stenographer.

Exit codes: 0 success; 1 unexpected error (traceback on stderr); 2 usage error (wrong
arguments, or OUTPUT_DIR not an empty directory); 3 input error (a source file is missing
or unreadable); 4 graph check failed (an ONNX graph does not match PyTorch, or tokens.txt
does not match the vocabulary).
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import sys
from decimal import Decimal, localcontext
from pathlib import Path

PRO_REPO = "ConwayResearch/Underdog-Bark-3.0-Pro"
PRO_REV = "4b5c51e04aa8d16dda9ecdff71bc29f7360149e4"

EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_CHECK = 4

REQUIRED_INPUTS = ("config.json", "model.safetensors", "tokenizer.json")
OUTPUTS = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
TMP_DIRNAME = ".tmp"
THREADS = 4
SEED = 0

#: fp32 graphs: largest max-abs difference, relative to the PyTorch output's max-abs value.
MAX_REL_DIFF_FP32 = 1e-3
#: int8 graphs: smallest mean cosine similarity to PyTorch along the feature axis. Weight
#: and activation int8 error on the random check input is too large for a max-abs rule,
#: but a broken graph or quantization drops the cosine far below this.
MIN_COSINE_INT8 = 0.8
#: Smallest share of joiner frames whose token argmax matches PyTorch.
MIN_JOINER_ARGMAX = {"": 1.0, ".int8": 0.8}


def _usage(message: str) -> int:
    print(f"bark_pro_to_sherpa: {message}", file=sys.stderr)
    print("usage: bark_pro_to_sherpa.py INPUT_DIR OUTPUT_DIR", file=sys.stderr)
    return EXIT_USAGE


def _check_inputs(src: Path) -> str | None:
    for name in REQUIRED_INPUTS:
        try:
            with (src / name).open("rb") as stream:
                stream.read(1)
        except OSError as exc:
            return f"{name}: {exc.strerror or exc}"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return _usage("expected exactly two arguments")
    src, out = Path(argv[0]), Path(argv[1])
    if not out.is_dir():
        return _usage(f"OUTPUT_DIR is not a directory: {out}")
    if any(out.iterdir()):
        return _usage(f"OUTPUT_DIR is not empty: {out}")
    problem = _check_inputs(src)
    if problem is not None:
        print(f"bark_pro_to_sherpa: input error: {problem}", file=sys.stderr)
        return EXIT_INPUT
    try:
        return _convert(src, out)
    finally:
        shutil.rmtree(out / TMP_DIRNAME, ignore_errors=True)


def _convert(src: Path, out: Path) -> int:
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization.matmul_nbits_quantizer import MatMulNBitsQuantizer
    from torch import nn
    from transformers import ParakeetForTDT

    # The quantizer logs one INFO line per graph node, thousands in all, and buries errors.
    logging.getLogger("onnxruntime.quantization.matmul_nbits_quantizer").setLevel(logging.WARNING)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(THREADS)

    # The export wrappers are plain nn.Module instances with an instance `forward`;
    # tracing calls that `forward`, and the submodules registered on each instance
    # become the graph's initializers.
    def module(forward, **children):
        wrapper = nn.Module()
        for name, child in children.items():
            setattr(wrapper, name, child)
        wrapper.forward = forward
        return wrapper.eval()

    def pointwise(conv):
        """Kernel-1 Conv1d as the equivalent MatMul so the int8 quantizer covers it."""
        wrapper = nn.Module()
        wrapper.weight = nn.Parameter(conv.weight.detach()[:, :, 0].clone(), requires_grad=False)
        wrapper.bias = None if conv.bias is None else nn.Parameter(conv.bias.detach().clone())
        wrapper.forward = lambda x: nn.functional.linear(
            x.transpose(1, 2), wrapper.weight, wrapper.bias
        ).transpose(1, 2)
        return wrapper

    def fold_norm(conv, norm):
        """Fold eval BatchNorm into the depthwise conv in float64, rounded once to float32.

        The exporter's own fold runs in float32 and rounds differently per CPU and torch
        build; IEEE float64 mul, div and sqrt give the same bytes on every machine.
        """
        scale = norm.weight.double() / torch.sqrt(norm.running_var.double() + norm.eps)
        bias = 0.0 if conv.bias is None else conv.bias.double()
        bias = (bias - norm.running_mean.double()) * scale + norm.bias.double()
        conv.weight = nn.Parameter((conv.weight.double() * scale[:, None, None]).float())
        conv.bias = nn.Parameter(bias.float())
        return nn.Identity()

    def exact_inv_freq(size):
        """transformers' 1 / 10000 ** (i / size) table, correctly rounded to float32.

        transformers computes it with float32 pow, whose last bits vary with the CPU
        kernel; Decimal power is correctly rounded, so the bytes are the same everywhere.
        """
        with localcontext(prec=40):
            values = [float(1 / Decimal(10000) ** (Decimal(i) / size)) for i in range(0, size, 2)]
        return torch.tensor(values, dtype=torch.float64).float()

    tmp = out / TMP_DIRNAME
    raw, fp32 = tmp / "raw", tmp / "fp32"
    raw.mkdir(parents=True)
    fp32.mkdir()

    model = ParakeetForTDT.from_pretrained(src, dtype=torch.float32, local_files_only=True).eval()
    model.config._attn_implementation = "eager"
    model.encoder.config._attn_implementation = "eager"
    for layer in model.encoder.layers:
        for name in ("pointwise_conv1", "pointwise_conv2"):
            setattr(layer.conv, name, pointwise(getattr(layer.conv, name)))
        with torch.no_grad():
            layer.conv.norm = fold_norm(layer.conv.depthwise_conv, layer.conv.norm)
    positions = model.encoder.encode_positions
    positions.inv_freq.copy_(exact_inv_freq(2 * positions.inv_freq.numel()))

    def encode(audio_signal, length):  # (N, 128, T) f32, (N,) i64
        x = audio_signal.transpose(1, 2)
        mask = (torch.arange(x.shape[1])[None, :] < length[:, None]).long()
        h = model.encoder(input_features=x, attention_mask=mask).last_hidden_state
        lens = model._get_subsampling_output_length(length).to(torch.int64)
        return h.transpose(1, 2), lens

    def decode(targets, target_length, h, c):
        d = model.decoder
        y, (h2, c2) = d.lstm(d.embedding(targets.to(torch.int64)), (h, c))
        return d.decoder_projector(y).transpose(1, 2), target_length, h2, c2

    def join(encoder_outputs, decoder_outputs):  # (N, 1024, T), (N, 640, U)
        f = model.encoder_projector(encoder_outputs.transpose(1, 2))
        g = decoder_outputs.transpose(1, 2)
        return model.joint.head(model.joint.activation(f[:, :, None, :] + g[:, None, :, :]))

    enc = module(encode, m=model)
    dec = module(decode, d=model.decoder)
    joi = module(join, proj=model.encoder_projector, joint=model.joint)
    blank = model.config.blank_token_id
    layers, hidden = model.config.num_decoder_layers, model.config.decoder_hidden_size

    with torch.no_grad():
        frames = 501
        torch.onnx.export(
            enc,
            (torch.randn(1, 128, frames), torch.tensor([frames])),
            str(raw / "encoder.onnx"),
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
            str(raw / "decoder.onnx"),
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
            str(raw / "joiner.onnx"),
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
        "comment": f"{PRO_REPO}@{PRO_REV}, CC-BY-4.0; int8 conversion by stenographer",
        "feat_dim": "128",
        "license": "CC-BY-4.0",
    }
    for name in ("encoder", "decoder", "joiner"):
        m = onnx.load(str(raw / f"{name}.onnx"))
        if name == "encoder":
            del m.metadata_props[:]
            for k, v in meta.items():
                p = m.metadata_props.add()
                p.key, p.value = k, v
            onnx.save(
                m,
                str(fp32 / "encoder.onnx"),
                save_as_external_data=True,
                all_tensors_to_one_file=True,
                location="encoder.weights",
                size_threshold=0,
            )
        else:
            onnx.save(m, str(fp32 / f"{name}.onnx"))
        # Saving with external data rewrites `m` in place; reload with absolute weight paths.
        m = onnx.load(str(fp32 / f"{name}.onnx"))
        q = MatMulNBitsQuantizer(m, bits=8, block_size=128, is_symmetric=True, accuracy_level=4)
        q.process()
        onnx.save(q.model.model, str(out / f"{name}.int8.onnx"))
        del m, q
    shutil.rmtree(raw)

    failures: list[str] = []
    tok = json.loads((src / "tokenizer.json").read_text(encoding="utf-8"))["model"]["vocab"]
    vocab = (
        [t for t, _ in sorted(tok.items(), key=lambda kv: kv[1])]
        if isinstance(tok, dict)
        else [t[0] for t in tok]
    )
    if len(vocab) != blank or any(" " in t or not t for t in vocab):
        failures.append(f"tokens: vocabulary has {len(vocab)} entries, blank id is {blank}")
    with open(out / "tokens.txt", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(f"{t} {i}\n" for i, t in enumerate(vocab))
        f.write(f"<blk> {blank}\n")

    # Graph check: each fp32 and int8 ONNX graph against PyTorch on the same seeded input.
    rng = np.random.default_rng(SEED)
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
        ref_j = joi(torch.from_numpy(ref_e[:, :, :5]), torch.from_numpy(ref_d)).numpy()
    for suffix, folder in (("", fp32), (".int8", out)):
        so = ort.SessionOptions()
        so.intra_op_num_threads = THREADS
        so.inter_op_num_threads = 1
        e = ort.InferenceSession(str(folder / f"encoder{suffix}.onnx"), so).run(
            None, {"audio_signal": x, "length": ln}
        )[0]
        d = ort.InferenceSession(str(folder / f"decoder{suffix}.onnx"), so).run(
            None,
            {
                "targets": tgt,
                "target_length": np.array([1], np.int32),
                "states.1": st,
                "states.2": st,
            },
        )[0]
        j = ort.InferenceSession(str(folder / f"joiner{suffix}.onnx"), so).run(
            None, {"encoder_outputs": ref_e[:, :, :5], "decoder_outputs": ref_d}
        )[0]
        label = suffix or ".fp32"
        # Feature axis of each output: (N, 1024, T), (N, 640, U), (N, T, U, vocab + durations).
        graphs = (("encoder", e, ref_e, 1), ("decoder", d, ref_d, 1), ("joiner", j, ref_j, -1))
        for name, a, b, axis in graphs:
            if a.shape != b.shape:
                failures.append(f"{name}{label}: shape {a.shape} != {b.shape}")
                continue
            rel = float(np.abs(a - b).max() / (np.abs(b).max() + 1e-9))
            dot = (a * b).sum(axis)
            norms = np.linalg.norm(a, axis=axis) * np.linalg.norm(b, axis=axis) + 1e-12
            cosine = float((dot / norms).mean())
            line = f"check {name}{label}: max rel diff {rel:.2e}, mean cosine {cosine:.4f}"
            if suffix == "" and rel > MAX_REL_DIFF_FP32:
                failures.append(f"{name}{label}: max rel diff {rel:.2e} > {MAX_REL_DIFF_FP32}")
            if suffix == ".int8" and cosine < MIN_COSINE_INT8:
                failures.append(f"{name}{label}: mean cosine {cosine:.4f} < {MIN_COSINE_INT8}")
            if name == "joiner":
                # Token logits only; the last five outputs are the TDT durations.
                tokens = slice(0, blank + 1)
                agree = float((a[..., tokens].argmax(-1) == b[..., tokens].argmax(-1)).mean())
                line += f", token argmax agreement {agree:.3f}"
                if agree < MIN_JOINER_ARGMAX[suffix]:
                    failures.append(
                        f"joiner{label}: argmax agreement {agree:.3f} < {MIN_JOINER_ARGMAX[suffix]}"
                    )
            print(line)
    if failures:
        for failure in failures:
            print(f"bark_pro_to_sherpa: graph check failed: {failure}", file=sys.stderr)
        return EXIT_CHECK
    for name in OUTPUTS:
        print(f"file {name} {(out / name).stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
