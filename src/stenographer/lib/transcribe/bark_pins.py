# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned sources, packages and outputs of the local Bark Pro conversion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    """One file of the source repo, fetched at the pinned revision."""

    path: str
    sha256: str

    @property
    def name(self) -> str:
        """Local file name in the source directory (``coreml/LICENSE`` -> ``LICENSE``)."""
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class BarkPins:
    repo: str
    revision: str
    sources: tuple[SourceFile, ...]
    torch_index_url: str
    packages: dict[str, str]
    #: sha256 of ``assets/convert/constraints.txt``, the full ``==`` lock of the venv.
    constraints_sha256: str
    outputs: dict[str, str]

    def source_url(self, source: SourceFile) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{source.path}"


BARK_PRO_PINS = BarkPins(
    repo="ConwayResearch/Underdog-Bark-3.0-Pro",
    revision="4b5c51e04aa8d16dda9ecdff71bc29f7360149e4",
    sources=(
        SourceFile(
            "config.json", "269282621d92eb22c3590fe0340530fec8a092d0387169bcd895c65541fa1ce0"
        ),
        SourceFile(
            "generation_config.json",
            "96e230a759fa74e65c36f654e5f9c909a426459d105e752f9003ddd7d328f8f3",
        ),
        SourceFile(
            "model.safetensors",
            "6f84b33e63ebd1851e910e8b2fe299d29f5e0efc6f57e84d92d2f79af464e0e5",
        ),
        SourceFile(
            "tokenizer.json", "bd321b096832a3f270bd3b2a88823957920f1a5c5ada71114a26ea729d0cbe91"
        ),
        SourceFile("NOTICE", "6bd6d22b4414b3ac97869dd8a97a813d668216ef66b04148ac858b988f8d063d"),
        # The pinned revision has no root LICENSE; coreml/LICENSE is the CC-BY-4.0 legal code.
        SourceFile(
            "coreml/LICENSE", "9ba9550ad48438d0836ddab3da480b3b69ffa0aac7b7878b5a0039e7ab429411"
        ),
    ),
    torch_index_url="https://download.pytorch.org/whl/cpu",
    packages={
        "torch": "2.14.1+cpu",
        "transformers": "5.20.2",
        "onnx": "1.23.2",
        "onnxruntime": "1.31.0",
        # onnxruntime 1.31 MatMulNBitsQuantizer imports onnx_ir without declaring it.
        "onnx-ir": "1.1.0",
        "numpy": "2.5.4",
    },
    constraints_sha256="eb6c43606d3a4e9c6bf68e680633030e22c28928a51ee7b421918f9395d45da7",
    # Two identical locked conversions on 2026-10-21 (task 32 evidence V7).
    outputs={
        "encoder.int8.onnx": "f111c3ad95637239021cc25b3166c0b6dbb64ab93854f8e9246d56e38b13a29e",
        "decoder.int8.onnx": "7c6ce4acf9282c323a5097467699fe2f2863142cff677b84426dc90fde7bd73f",
        "joiner.int8.onnx": "21674f569e8f102d6c5e10c222fabea73cafb171bace666f33bb2a1b4d0067a2",
        "tokens.txt": "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
    },
)
