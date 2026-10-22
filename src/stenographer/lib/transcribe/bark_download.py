# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit local conversion and install of the Bark Pro int8 model.

The download builds the model on this machine: a temporary venv made with the
system Python 3 gets the pinned converter packages, the pinned source files come
over HTTPS, the converter asset writes the int8 files, and the finished directory
moves into place with one ``os.replace``. Every file is checked against its pinned
sha256. The venv and the BF16 source are deleted on success and on failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

from stenographer.lib.transcribe.bark_pins import BARK_PRO_PINS, BarkPins
from stenographer.lib.transcribe.errors import BarkDownloadError

if TYPE_CHECKING:
    from collections.abc import Callable

    from stenographer.lib.platform.command_runner import CommandRunner

MODEL_DIRNAME = "bark-pro-int8"
SYSTEM_PYTHON = "/usr/bin/python3"
#: Measured end-to-end peak on 2026-10-21: 6.91 GiB (7,422,359,945 bytes).
MIN_FREE_BYTES = 8 * 1024**3
MANIFEST_SCHEMA = 1
CONVERTED_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
NOTICE_MODIFICATION = (
    "Converted to ONNX and quantized to int8 (weight-only) on the user's machine by stenographer."
)
VENV_FIX = "Run `sudo apt install python3-venv`, then retry."
ATTRIBUTION = (
    "Underdog Bark 3.0 Pro by Conway Research (CC BY 4.0), converted to int8 ONNX on this machine"
)

#: What each non-zero converter exit code means, with the fix.
CONVERTER_ERRORS = {
    1: "the converter stopped with an unexpected error (see the traceback above). "
    "Retry; report the traceback if it repeats.",
    2: "the converter was called with wrong arguments or a non-empty output directory. "
    "This is a stenographer bug; please report it.",
    3: "the converter could not read a source file. Retry the download.",
    4: "the converted ONNX graphs do not match the PyTorch model (graph check failed). "
    "Nothing was installed; report this with the output above.",
}

#: Imports that ``python3 -m venv`` needs; Ubuntu ships ensurepip in python3-venv.
_VENV_PROBE = (
    "import importlib.util, sys; "
    "sys.exit(0 if all(importlib.util.find_spec(m) for m in ('venv', 'ensurepip')) else 1)"
)


def asr_root(data_dir: Path) -> Path:
    return data_dir / "models" / "asr"


def model_dir(data_dir: Path) -> Path:
    return asr_root(data_dir) / MODEL_DIRNAME


def _default_data_dir() -> Path:
    from stenographer.lib.platform import current_platform

    return current_platform().data_dir(os.environ, Path.home())


def _default_runner() -> CommandRunner:
    from stenographer.lib.platform import current_platform

    return current_platform().command_runner()


def _fetch(url: str, destination: Path) -> None:
    with urlopen(url, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, 1024 * 1024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def converter_path() -> Path:
    return Path(str(files("stenographer"))) / "assets" / "convert" / "bark_pro_to_sherpa.py"


def constraints_path() -> Path:
    """The full ``==`` lock of the converter venv, applied with ``pip install -c``."""
    return Path(str(files("stenographer"))) / "assets" / "convert" / "constraints.txt"


def venv_available(python: str = SYSTEM_PYTHON, runner: CommandRunner | None = None) -> bool:
    """True when ``python -m venv`` can create a venv with pip. No writes, no network."""
    runner = runner if runner is not None else _default_runner()
    return runner.run_quiet([python, "-I", "-c", _VENV_PROBE]) == 0


def has_free_space(free_bytes: int, required: int = MIN_FREE_BYTES) -> bool:
    """PURE: the free-space rule for the temporary build."""
    return free_bytes >= required


def build_manifest(pins: BarkPins, file_hashes: dict[str, str]) -> dict:
    """PURE: the ``manifest.json`` content for an installed model."""
    return {
        "schema": MANIFEST_SCHEMA,
        "source": {"repo": pins.repo, "revision": pins.revision},
        "packages": dict(pins.packages),
        "files": dict(file_hashes),
    }


def parse_manifest(text: str) -> dict | None:
    """PURE: the manifest as a dict, or None when it is not a valid schema-1 manifest."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA:
        return None
    source, listed = data.get("source"), data.get("files")
    if not isinstance(source, dict) or not isinstance(source.get("revision"), str):
        return None
    if not isinstance(listed, dict) or not listed:
        return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in listed.items()):
        return None
    return data


def is_model_cached(data_dir: Path | None = None, *, pins: BarkPins = BARK_PRO_PINS) -> bool:
    """True when the installed model's manifest names the pinned revision and its files exist.

    It does not hash the files, so the probe stays fast; the download hashes them.
    """
    root = model_dir(data_dir if data_dir is not None else _default_data_dir())
    try:
        manifest = parse_manifest((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    if manifest is None or manifest["source"]["revision"] != pins.revision:
        return False
    return all(
        "/" not in name and name not in ("", ".", "..") and (root / name).is_file()
        for name in manifest["files"]
    )


def _install_packages(
    venv_python: str, pins: BarkPins, runner: CommandRunner, constraints: Path
) -> None:
    if not constraints.is_file() or _sha256(constraints) != pins.constraints_sha256:
        raise BarkDownloadError(
            f"Package install failed: {constraints} does not match its pinned sha256. "
            "Reinstall stenographer, then retry."
        )
    pip = [
        venv_python,
        "-I",
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "-c",
        str(constraints),
    ]
    others = [f"{name}=={version}" for name, version in pins.packages.items() if name != "torch"]
    steps = (
        [*pip, "--index-url", pins.torch_index_url, f"torch=={pins.packages['torch']}"],
        [*pip, *others],
    )
    for argv in steps:
        if runner.run(argv) != 0:
            raise BarkDownloadError(
                "Package install failed: pip could not install the pinned converter packages "
                f"({', '.join(f'{k}=={v}' for k, v in pins.packages.items())}). "
                "Check the network connection and that wheels exist for the system Python 3, "
                "then retry."
            )


def _fetch_sources(source_dir: Path, pins: BarkPins, fetch: Callable[[str, Path], None]) -> None:
    for source in pins.sources:
        destination = source_dir / source.name
        try:
            fetch(pins.source_url(source), destination)
        except Exception as exc:
            raise BarkDownloadError(
                f"Source download failed for {source.path}: {exc}. "
                "Check the network connection, then retry."
            ) from exc
        if _sha256(destination) != source.sha256:
            raise BarkDownloadError(
                f"Source file {source.path} failed its sha256 check. Nothing was installed. "
                "Retry; if it repeats, the upstream file changed."
            )


def _check_outputs(out_dir: Path, pins: BarkPins) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in CONVERTED_FILES:
        path = out_dir / name
        actual = _sha256(path) if path.is_file() else None
        if actual is None or actual != pins.outputs.get(name):
            raise BarkDownloadError(
                f"Output file {name} does not match its pinned sha256. Nothing was installed. "
                "The conversion is not reproducible on this machine; please report it."
            )
        hashes[name] = actual
    return hashes


def _write_attribution(out_dir: Path, source_dir: Path) -> dict[str, str]:
    notice = source_dir / "NOTICE"
    text = notice.read_text(encoding="utf-8").rstrip("\n")
    (out_dir / "NOTICE").write_text(f"{text}\n\n{NOTICE_MODIFICATION}\n", encoding="utf-8")
    shutil.copyfile(source_dir / "LICENSE", out_dir / "LICENSE")
    return {name: _sha256(out_dir / name) for name in ("NOTICE", "LICENSE")}


def _install(out_dir: Path, target: Path, build_dir: Path) -> None:
    if target.exists():
        # A stale or partial model: move it into the build dir so cleanup deletes it.
        os.replace(target, build_dir / "previous")
    os.replace(out_dir, target)


def download_bark_pro(
    data_dir: Path,
    *,
    runner: CommandRunner | None = None,
    fetch: Callable[[str, Path], None] = _fetch,
    python: str = SYSTEM_PYTHON,
    pins: BarkPins = BARK_PRO_PINS,
    converter: Path | None = None,
    constraints: Path | None = None,
    min_free_bytes: int = MIN_FREE_BYTES,
    on_step: Callable[[str], None] = lambda _line: None,
) -> bool:
    """Build and install the model. Return False when it is already present, True when built.

    Failure checks run in this order: venv, free space, package install, source sha256,
    converter exit code, output sha256. The first two run before any network call.
    """
    if is_model_cached(data_dir, pins=pins):
        return False
    runner = runner if runner is not None else _default_runner()
    if not venv_available(python, runner):
        raise BarkDownloadError(f"Venv check failed: `{python} -m venv` does not work. {VENV_FIX}")
    root = asr_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if not has_free_space(free, min_free_bytes):
        raise BarkDownloadError(
            f"Free-space check failed: {free / 1024**3:.1f} GiB free at {root}, "
            f"{min_free_bytes / 1024**3:.0f} GiB needed for the temporary build. "
            "Free some disk space, then retry."
        )

    build_dir = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        venv_dir, source_dir, out_dir = build_dir / "venv", build_dir / "source", build_dir / "out"
        source_dir.mkdir()
        out_dir.mkdir()
        on_step("creating a temporary venv with the system Python 3")
        if runner.run([python, "-m", "venv", str(venv_dir)]) != 0:
            raise BarkDownloadError(
                f"Venv creation failed: `{python} -m venv` could not create {venv_dir}. {VENV_FIX}"
            )
        venv_python = str(venv_dir / "bin" / "python")
        on_step("installing the pinned converter packages (not cached)")
        lock = constraints if constraints is not None else constraints_path()
        _install_packages(venv_python, pins, runner, lock)
        on_step(f"downloading {pins.repo} at {pins.revision[:12]} (about 1.3 GB)")
        _fetch_sources(source_dir, pins, fetch)
        on_step("converting to int8 ONNX (about a minute; longer on slower machines)")
        script = converter if converter is not None else converter_path()
        code = runner.run([venv_python, "-I", str(script), str(source_dir), str(out_dir)])
        if code != 0:
            meaning = CONVERTER_ERRORS.get(code, f"the converter exited with code {code}.")
            raise BarkDownloadError(f"Conversion failed: {meaning}")
        hashes = _check_outputs(out_dir, pins)
        hashes.update(_write_attribution(out_dir, source_dir))
        manifest = build_manifest(pins, hashes)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        _install(out_dir, model_dir(data_dir), build_dir)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    return True
