# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bark Pro converter asset: its usage and input exit codes, run as a real subprocess.

These paths exit before the converter imports torch, so they run in the test venv.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys

from stenographer.lib.transcribe.bark_download import (
    CONVERTED_FILES,
    constraints_path,
    converter_path,
)
from stenographer.lib.transcribe.bark_pins import BARK_PRO_PINS


def _convert(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(converter_path()), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_wrong_arguments_exit_2():
    result = _convert("only-one")

    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_a_non_empty_output_dir_exits_2_and_is_left_alone(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("user file")

    result = _convert(tmp_path / "src", out)

    assert result.returncode == 2
    assert "not empty" in result.stderr
    assert [p.name for p in out.iterdir()] == ["keep.txt"]


def test_a_missing_output_dir_exits_2(tmp_path):
    result = _convert(tmp_path, tmp_path / "absent")

    assert result.returncode == 2


def test_a_missing_source_file_exits_3_and_names_it(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "config.json").write_text("{}")
    (src / "tokenizer.json").write_text("{}")

    result = _convert(src, out)

    assert result.returncode == 3
    assert "model.safetensors" in result.stderr
    assert list(out.iterdir()) == []


def test_the_converter_imports_only_stdlib_and_pinned_packages_never_stenographer():
    tree = ast.parse(converter_path().read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    third_party = roots - set(sys.stdlib_module_names)

    assert third_party == {"numpy", "onnx", "onnxruntime", "torch", "transformers"}
    assert third_party <= set(BARK_PRO_PINS.packages)


def test_the_converter_names_the_pinned_revision_and_the_download_outputs():
    namespace: dict = {}
    tree = ast.parse(converter_path().read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else None
        if isinstance(target, ast.Name) and target.id in {"PRO_REPO", "PRO_REV", "OUTPUTS"}:
            namespace[target.id] = ast.literal_eval(node.value)

    assert namespace["PRO_REPO"] == BARK_PRO_PINS.repo
    assert namespace["PRO_REV"] == BARK_PRO_PINS.revision
    assert namespace["OUTPUTS"] == CONVERTED_FILES


def _lock() -> dict[str, str]:
    lines = constraints_path().read_text(encoding="utf-8").splitlines()
    pairs = [line.split("==") for line in lines if line and not line.startswith("#")]
    return {name.lower().replace("_", "-"): version for name, version in pairs}


def test_the_lock_file_matches_its_pinned_sha256():
    digest = hashlib.sha256(constraints_path().read_bytes()).hexdigest()

    assert digest == BARK_PRO_PINS.constraints_sha256


def test_the_lock_pins_every_package_exactly_without_hashes():
    lines = [
        line
        for line in constraints_path().read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert lines
    assert all(line.count("==") == 1 and " " not in line for line in lines)
    assert not [line for line in lines if "--hash" in line or "@" in line]


def test_the_lock_agrees_with_every_top_level_pin():
    lock = _lock()

    for name, version in BARK_PRO_PINS.packages.items():
        assert lock[name] == version, name
