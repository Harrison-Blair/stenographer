# SPDX-License-Identifier: GPL-3.0-or-later
"""Add per-clip mean subtraction to the WeSpeaker ResNet34-LM speaker model.

The model expects Kaldi fbank features with the mean over time subtracted. sherpa-onnx
gives it the features without that step, so this script adds it as the first nodes of the
graph. Maintainers run it to rebuild the file of the ``speaker-models-1`` release:

    python -I scripts/speaker_model_mean.py SOURCE.onnx OUTPUT.onnx

SOURCE.onnx is ``wespeaker_en_voxceleb_resnet34_LM.onnx`` from
https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models; the script
checks its sha256. The Python environment needs the ``onnx`` package (tested with 1.23.2).
The script changes nothing else in the graph and keeps the metadata that sherpa-onnx reads.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import onnx
from onnx import helper

SOURCE_SHA256 = "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"
_INPUT = "feats"
_MEAN = "stenographer_feats_mean"
_CENTERED = "stenographer_feats_centered"


def add_mean_subtraction(model: onnx.ModelProto) -> onnx.ModelProto:
    """Return *model* with the mean over time of ``feats`` (B, T, 80) subtracted first."""
    graph = model.graph
    if [graph_input.name for graph_input in graph.input] != [_INPUT]:
        raise ValueError(f"the model must have the one input {_INPUT!r}")
    if any(node.output[0] in (_MEAN, _CENTERED) for node in graph.node):
        raise ValueError("the model already subtracts the mean")
    for node in graph.node:
        node.input[:] = [_CENTERED if name == _INPUT else name for name in node.input]
    # ReduceMean takes its axes as an attribute up to opset 17.
    mean = helper.make_node("ReduceMean", [_INPUT], [_MEAN], axes=[1], keepdims=1)
    centered = helper.make_node("Sub", [_INPUT, _MEAN], [_CENTERED])
    nodes = [mean, centered, *graph.node]
    del graph.node[:]
    graph.node.extend(nodes)
    helper.set_model_props(
        model,
        {
            **{prop.key: prop.value for prop in model.metadata_props},
            "comment": "mean subtraction added to the ONNX graph by stenographer",
        },
    )
    onnx.checker.check_model(model, full_check=True)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    content = args.source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"source sha256 is {digest}, expected {SOURCE_SHA256}")
    model = add_mean_subtraction(onnx.load_from_string(content))
    args.output.write_bytes(model.SerializeToString())
    print(args.output, hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
