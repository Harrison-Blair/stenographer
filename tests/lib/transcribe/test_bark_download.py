# SPDX-License-Identifier: GPL-3.0-or-later
"""Bark Pro download: manifest probe, check order, fail-closed hashes, cleanup, atomic install.

The subprocess and network seams are fakes; the file system is real (``tmp_path``).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from stenographer.lib.transcribe import bark_download
from stenographer.lib.transcribe.bark_download import (
    build_manifest,
    download_bark_pro,
    has_free_space,
    is_model_cached,
    parse_manifest,
    venv_available,
)
from stenographer.lib.transcribe.bark_pins import BARK_PRO_PINS, BarkPins, SourceFile
from stenographer.lib.transcribe.errors import BarkDownloadError

REVISION = "0123456789abcdef0123456789abcdef01234567"

SOURCE_BYTES = {
    "config.json": b'{"blank_token_id": 2}',
    "model.safetensors": b"weights",
    "tokenizer.json": b"{}",
    "NOTICE": b"Upstream notice.\n",
    "coreml/LICENSE": b"Attribution 4.0 International\n",
}

CONVERTED_BYTES = {
    "encoder.int8.onnx": b"encoder",
    "decoder.int8.onnx": b"decoder",
    "joiner.int8.onnx": b"joiner",
    "tokens.txt": b"a 0\nb 1\n<blk> 2\n",
}


LOCK_BYTES = b"numpy==3.0\ntorch==1.0+cpu\ntransformers==2.0\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pins(**overrides) -> BarkPins:
    fields = {
        "repo": "acme/bark",
        "revision": REVISION,
        "sources": tuple(SourceFile(path, _sha(data)) for path, data in SOURCE_BYTES.items()),
        "torch_index_url": "https://torch.example/cpu",
        "packages": {"torch": "1.0+cpu", "transformers": "2.0", "numpy": "3.0"},
        "constraints_sha256": _sha(LOCK_BYTES),
        "outputs": {name: _sha(data) for name, data in CONVERTED_BYTES.items()},
    }
    fields.update(overrides)
    return BarkPins(**fields)


class Host:
    """Fake subprocess and network seams that record every call."""

    def __init__(self, *, probe_code=0, venv_code=0, pip_code=0, converter_code=0, outputs=None):
        self.calls: list[str] = []
        self.argv: list[list[str]] = []
        self.probe_code = probe_code
        self.venv_code = venv_code
        self.pip_code = pip_code
        self.converter_code = converter_code
        self.outputs = CONVERTED_BYTES if outputs is None else outputs
        self.sources: dict[str, bytes] = {}

    def run_quiet(self, argv):
        self.calls.append("probe")
        return self.probe_code

    def run(self, argv):
        argv = list(argv)
        self.argv.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            self.calls.append("venv")
            return self.venv_code
        if "pip" in argv:
            self.calls.append("pip")
            return self.pip_code
        self.calls.append("convert")
        out_dir = Path(argv[-1])
        for name, data in self.outputs.items():
            (out_dir / name).write_bytes(data)
        return self.converter_code

    def fetch(self, url, destination):
        self.calls.append(f"fetch:{url.rsplit('/', 1)[-1]}")
        path = url.split(f"/resolve/{REVISION}/", 1)[1]
        destination.write_bytes(self.sources.get(path, SOURCE_BYTES[path]))


def _lock(tmp_path, data=LOCK_BYTES, name="constraints.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _download(tmp_path, host, **kwargs):
    kwargs.setdefault("pins", _pins())
    kwargs.setdefault("min_free_bytes", 0)
    kwargs.setdefault("constraints", _lock(tmp_path))
    return download_bark_pro(
        tmp_path,
        runner=host,
        fetch=host.fetch,
        python="/usr/bin/python3",
        converter=Path("/assets/bark_pro_to_sherpa.py"),
        **kwargs,
    )


def _asr_entries(tmp_path) -> list[str]:
    root = tmp_path / "models" / "asr"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def _write_model(tmp_path, *, revision=REVISION, files=("encoder.int8.onnx", "tokens.txt")):
    model = tmp_path / "models" / "asr" / "bark-pro-int8"
    model.mkdir(parents=True)
    for name in files:
        (model / name).write_text("not hashed")
    manifest = {
        "schema": 1,
        "source": {"repo": "acme/bark", "revision": revision},
        "packages": {},
        "files": {name: "0" * 64 for name in files},
    }
    (model / "manifest.json").write_text(json.dumps(manifest))
    return model


# --- manifest and is_model_cached ---


def test_parse_manifest_accepts_the_schema_1_shape():
    text = json.dumps(build_manifest(_pins(), {"tokens.txt": "ab"}))

    parsed = parse_manifest(text)

    assert parsed is not None
    assert parsed["source"] == {"repo": "acme/bark", "revision": REVISION}
    assert parsed["files"] == {"tokens.txt": "ab"}
    assert parsed["packages"] == {"torch": "1.0+cpu", "transformers": "2.0", "numpy": "3.0"}


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        json.dumps({"schema": 2, "source": {"revision": REVISION}, "files": {"a": "b"}}),
        json.dumps({"schema": 1, "source": {}, "files": {"a": "b"}}),
        json.dumps({"schema": 1, "source": {"revision": REVISION}, "files": {}}),
        json.dumps({"schema": 1, "source": {"revision": REVISION}, "files": {"a": 3}}),
    ],
)
def test_parse_manifest_rejects_malformed_manifests(text):
    assert parse_manifest(text) is None


def test_a_model_with_a_matching_manifest_and_all_files_is_cached(tmp_path):
    _write_model(tmp_path)

    assert is_model_cached(tmp_path, pins=_pins()) is True


def test_is_model_cached_does_not_hash_the_files(tmp_path):
    # The manifest hashes are all zeros and the files hold other bytes.
    _write_model(tmp_path)

    assert is_model_cached(tmp_path, pins=_pins()) is True


def test_a_manifest_for_another_revision_is_not_cached(tmp_path):
    _write_model(tmp_path, revision="f" * 40)

    assert is_model_cached(tmp_path, pins=_pins()) is False


def test_a_missing_listed_file_is_not_cached(tmp_path):
    model = _write_model(tmp_path)
    (model / "tokens.txt").unlink()

    assert is_model_cached(tmp_path, pins=_pins()) is False


def test_no_model_directory_or_a_corrupt_manifest_is_not_cached(tmp_path):
    assert is_model_cached(tmp_path, pins=_pins()) is False
    model = _write_model(tmp_path)
    (model / "manifest.json").write_text("{")

    assert is_model_cached(tmp_path, pins=_pins()) is False


def test_a_manifest_cannot_point_outside_the_model_directory(tmp_path):
    _write_model(tmp_path, files=("../asr",))

    assert is_model_cached(tmp_path, pins=_pins()) is False


# --- pure rules and the real venv probe ---


def test_free_space_rule_needs_at_least_ten_gib():
    # Real end-to-end peaks: 6.91 GiB (2026-10-21) and 7.52 GiB.
    assert bark_download.MIN_FREE_BYTES == 10 * 1024**3
    assert has_free_space(10 * 1024**3) is True
    assert has_free_space(10 * 1024**3 - 1) is False


def test_venv_probe_passes_for_a_python_with_venv_and_ensurepip():
    assert venv_available(sys.executable) is True


def test_venv_probe_fails_for_a_python_that_does_not_exist(tmp_path):
    assert venv_available(str(tmp_path / "python3")) is False


# --- check order ---


def test_venv_check_fails_first_with_the_apt_fix_and_no_network(tmp_path):
    host = Host(probe_code=1)

    with pytest.raises(
        BarkDownloadError, match=r"Venv check failed.*sudo apt install python3-venv"
    ):
        _download(tmp_path, host, min_free_bytes=10**30)

    assert host.calls == ["probe"]
    assert _asr_entries(tmp_path) == []


def test_free_space_check_runs_after_the_venv_check_and_before_any_network(tmp_path):
    host = Host()

    with pytest.raises(
        BarkDownloadError, match=r"Free-space check failed: .* GiB free at .* GiB needed"
    ):
        _download(tmp_path, host, min_free_bytes=10**30)

    assert host.calls == ["probe"]
    assert _asr_entries(tmp_path) == []


def test_steps_run_in_the_spec_order(tmp_path):
    host = Host()

    assert _download(tmp_path, host) is True

    assert host.calls == [
        "probe",
        "venv",
        "pip",
        "pip",
        "fetch:config.json",
        "fetch:model.safetensors",
        "fetch:tokenizer.json",
        "fetch:NOTICE",
        "fetch:LICENSE",
        "convert",
    ]


def test_packages_install_pinned_without_a_wheel_cache(tmp_path):
    host = Host()

    _download(tmp_path, host)

    venv_python = host.argv[1][0]
    assert venv_python.endswith("/venv/bin/python")
    torch, others = host.argv[1], host.argv[2]
    lock = str(tmp_path / "constraints.txt")
    for argv in (torch, others):
        assert argv[:4] == [venv_python, "-I", "-m", "pip"]
        assert "--no-cache-dir" in argv
        assert argv[argv.index("-c") + 1] == lock
    assert torch[-3:] == ["--index-url", "https://torch.example/cpu", "torch==1.0+cpu"]
    assert others[-2:] == ["transformers==2.0", "numpy==3.0"]
    assert "--index-url" not in others


def test_the_converter_runs_isolated_on_the_source_and_an_empty_output_dir(tmp_path):
    host = Host()

    _download(tmp_path, host)

    argv = host.argv[-1]
    assert argv[1:3] == ["-I", "/assets/bark_pro_to_sherpa.py"]
    assert Path(argv[3]).name == "source"
    assert Path(argv[4]).name == "out"


def test_a_changed_lock_file_fails_the_package_step_before_pip_runs(tmp_path):
    host = Host()

    with pytest.raises(BarkDownloadError, match=r"Package install failed: .*changed\.txt"):
        _download(tmp_path, host, constraints=_lock(tmp_path, b"numpy==9.9\n", "changed.txt"))

    assert "pip" not in host.calls
    assert not [call for call in host.calls if call.startswith("fetch")]
    assert _asr_entries(tmp_path) == []


def test_a_failed_package_install_stops_before_the_source_download(tmp_path):
    host = Host(pip_code=1)

    with pytest.raises(BarkDownloadError, match=r"Package install failed"):
        _download(tmp_path, host)

    assert not [call for call in host.calls if call.startswith("fetch")]
    assert _asr_entries(tmp_path) == []


def test_a_source_sha256_mismatch_names_the_file_and_installs_nothing(tmp_path):
    host = Host()
    host.sources["model.safetensors"] = b"tampered"

    with pytest.raises(BarkDownloadError, match=r"model\.safetensors failed its sha256 check"):
        _download(tmp_path, host)

    assert "convert" not in host.calls
    assert _asr_entries(tmp_path) == []


def test_a_network_error_names_the_source_file(tmp_path):
    host = Host()

    def fail(url, destination):
        raise OSError("no route to host")

    with pytest.raises(BarkDownloadError, match=r"Source download failed for config\.json"):
        download_bark_pro(
            tmp_path,
            runner=host,
            fetch=fail,
            pins=_pins(),
            min_free_bytes=0,
            constraints=_lock(tmp_path),
        )

    assert _asr_entries(tmp_path) == []


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (1, r"Conversion failed: the converter stopped with an unexpected error"),
        (2, r"Conversion failed: the converter was called with wrong arguments"),
        (3, r"Conversion failed: the converter could not read a source file"),
        (4, r"Conversion failed: .*graph check failed"),
        (9, r"Conversion failed: the converter exited with code 9"),
    ],
)
def test_each_converter_exit_code_has_its_message_and_installs_nothing(tmp_path, code, message):
    host = Host(converter_code=code)

    with pytest.raises(BarkDownloadError, match=message):
        _download(tmp_path, host)

    assert _asr_entries(tmp_path) == []


def test_an_output_sha256_mismatch_fails_closed_and_names_the_file(tmp_path):
    host = Host(outputs={**CONVERTED_BYTES, "joiner.int8.onnx": b"different"})

    with pytest.raises(BarkDownloadError, match=r"Output file joiner\.int8\.onnx does not match"):
        _download(tmp_path, host)

    assert _asr_entries(tmp_path) == []


def test_unpinned_outputs_fail_closed(tmp_path):
    host = Host()

    with pytest.raises(BarkDownloadError, match=r"Output file encoder\.int8\.onnx"):
        _download(tmp_path, host, pins=_pins(outputs={}))

    assert _asr_entries(tmp_path) == []


def test_a_missing_output_fails_closed(tmp_path):
    outputs = dict(CONVERTED_BYTES)
    del outputs["tokens.txt"]
    host = Host(outputs=outputs)

    with pytest.raises(BarkDownloadError, match=r"Output file tokens\.txt"):
        _download(tmp_path, host)

    assert _asr_entries(tmp_path) == []


# --- install ---


def test_a_successful_download_installs_exactly_the_model_files(tmp_path):
    host = Host()

    assert _download(tmp_path, host) is True

    assert _asr_entries(tmp_path) == ["bark-pro-int8"]
    model = tmp_path / "models" / "asr" / "bark-pro-int8"
    assert sorted(p.name for p in model.iterdir()) == [
        "LICENSE",
        "NOTICE",
        "decoder.int8.onnx",
        "encoder.int8.onnx",
        "joiner.int8.onnx",
        "manifest.json",
        "tokens.txt",
    ]
    assert (model / "LICENSE").read_bytes() == SOURCE_BYTES["coreml/LICENSE"]
    notice = (model / "NOTICE").read_text()
    assert notice == (
        "Upstream notice.\n\n"
        "Converted to ONNX and quantized to int8 (weight-only) on the user's machine "
        "by stenographer.\n"
    )
    manifest = json.loads((model / "manifest.json").read_text())
    assert manifest["schema"] == 1
    assert manifest["source"] == {"repo": "acme/bark", "revision": REVISION}
    assert manifest["packages"] == {"torch": "1.0+cpu", "transformers": "2.0", "numpy": "3.0"}
    expected = {name: _sha(data) for name, data in CONVERTED_BYTES.items()}
    expected["NOTICE"] = _sha(notice.encode())
    expected["LICENSE"] = _sha(SOURCE_BYTES["coreml/LICENSE"])
    assert manifest["files"] == expected
    assert is_model_cached(tmp_path, pins=_pins()) is True


def test_a_present_model_is_not_rebuilt(tmp_path):
    _download(tmp_path, Host())
    host = Host()

    assert _download(tmp_path, host) is False

    assert host.calls == []


def test_a_stale_model_directory_is_replaced_atomically(tmp_path):
    stale = _write_model(tmp_path, revision="f" * 40)
    (stale / "leftover.bin").write_text("old")

    assert _download(tmp_path, Host()) is True

    model = tmp_path / "models" / "asr" / "bark-pro-int8"
    assert not (model / "leftover.bin").exists()
    assert _asr_entries(tmp_path) == ["bark-pro-int8"]


def test_a_failed_rebuild_keeps_no_partial_model_and_leaves_the_stale_one(tmp_path):
    stale = _write_model(tmp_path, revision="f" * 40)
    host = Host(converter_code=4)

    with pytest.raises(BarkDownloadError):
        _download(tmp_path, host)

    assert _asr_entries(tmp_path) == ["bark-pro-int8"]
    assert sorted(p.name for p in stale.iterdir()) == [
        "encoder.int8.onnx",
        "manifest.json",
        "tokens.txt",
    ]


def test_an_unexpected_error_still_deletes_the_build_directory(tmp_path):
    host = Host()

    def explode(url, destination):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        download_bark_pro(
            tmp_path,
            runner=host,
            fetch=explode,
            pins=_pins(),
            min_free_bytes=0,
            constraints=_lock(tmp_path),
        )

    assert _asr_entries(tmp_path) == []


# --- pins ---


def test_pins_name_the_spec_revision_and_every_converter_package():
    assert BARK_PRO_PINS.repo == "ConwayResearch/Underdog-Bark-3.0-Pro"
    assert BARK_PRO_PINS.revision == "4b5c51e04aa8d16dda9ecdff71bc29f7360149e4"
    assert set(BARK_PRO_PINS.packages) == {
        "torch",
        "transformers",
        "onnx",
        "onnxruntime",
        "onnx-ir",
        "numpy",
    }
    assert BARK_PRO_PINS.packages["torch"].endswith("+cpu")
    names = {source.name for source in BARK_PRO_PINS.sources}
    assert {"config.json", "model.safetensors", "tokenizer.json", "NOTICE", "LICENSE"} <= names
    assert set(BARK_PRO_PINS.outputs) == set(bark_download.CONVERTED_FILES)


def test_source_urls_are_pinned_https_resolve_urls():
    source = BARK_PRO_PINS.sources[0]

    assert BARK_PRO_PINS.source_url(source) == (
        "https://huggingface.co/ConwayResearch/Underdog-Bark-3.0-Pro/resolve/"
        f"4b5c51e04aa8d16dda9ecdff71bc29f7360149e4/{source.path}"
    )
