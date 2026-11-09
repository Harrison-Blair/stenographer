# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: F821 - Analysis/PYZ/EXE/COLLECT/SPECPATH are injected by PyInstaller
# PyInstaller spec for stenographer.
#
# Build: scripts/build.sh
# Direct: .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec
# Output: dist/stenographer/stenographer  (onedir bundle)
#
# Deliberately NOT bundled — the target system must provide (see docs/building.md):
#   - libportaudio / pipewire / pulse libs (excluded by hook-sounddevice.py;
#     found at runtime via rthooks/py_rth_portaudio.py)
#   - wl-copy, canberra-gtk-play / pw-play / paplay CLIs; /dev/uinput access + `input` group
# The ASR model is never bundled; `stenographer model download` builds it in the
# local model directory. The voice models ship in assets/models; the speaker
# model GGUF is fetched there by scripts/fetch_speaker_model.py before the build.
# The NeMo-Speech runtime ships for the build architecture only, as data files
# in one folder: its libraries load each other through RPATH $ORIGIN, and as
# data PyInstaller does not copy them a second time into _internal/.

# -*- mode: python ; coding: utf-8 -*-
import platform
import sys
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets"
SPEAKER_MODEL = ASSET_SRC / "models" / "Nemotron-3-Diarization.q8_0.gguf"
if not SPEAKER_MODEL.is_file():
    raise RuntimeError(f"{SPEAKER_MODEL} is missing; run scripts/fetch_speaker_model.py")
NEMO_RUNTIME = f"nemo_speech/linux-{platform.machine()}"
if sys.platform == "linux" and not (ASSET_SRC / NEMO_RUNTIME).is_dir():
    raise RuntimeError(f"no NeMo-Speech runtime for this architecture: {NEMO_RUNTIME}")
ASSET_DATAS = [
    (str(path), str(Path("stenographer/assets") / path.parent.relative_to(ASSET_SRC)))
    for path in sorted(ASSET_SRC.rglob("*"))
    if path.is_file()
    and (
        not path.relative_to(ASSET_SRC).as_posix().startswith("nemo_speech/linux-")
        or path.parent.relative_to(ASSET_SRC).as_posix() == NEMO_RUNTIME
    )
]
TEXTUAL_DATAS, TEXTUAL_BINARIES, TEXTUAL_IMPORTS = collect_all("textual")
SHERPA_DATAS, SHERPA_BINARIES, SHERPA_IMPORTS = collect_all("sherpa_onnx")
NATIVE_BINARIES = []
NATIVE_IMPORTS = []
if sys.platform == "linux":
    ffi_spec = find_spec("pywayland._ffi")
    if ffi_spec is None or ffi_spec.origin is None:
        raise RuntimeError("PyWayland CFFI extension is missing; reinstall pywayland==0.4.18")
    ffi = Path(ffi_spec.origin)
    NATIVE_BINARIES = [(str(ffi), "pywayland")] + [
        (path, ".") for name, path in get_imports(ffi)
        if path is not None and (name.startswith("libwayland-") or name.startswith("libffi."))
    ]
    NATIVE_IMPORTS = ["evdev", "evdev._ecodes", "pywayland._ffi"]

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    # Explicit collection keeps the completed PyWayland CFFI build and lets
    # PyInstaller trace its libwayland/libffi shared-library dependencies.
    binaries=[*NATIVE_BINARIES, *TEXTUAL_BINARIES, *SHERPA_BINARIES],
    datas=[
        # Sound cues, the overlay quill, Caveat variable font and OFL, and the
        # Bark Pro converter script and its venv lock (assets/convert/).
        *ASSET_DATAS,
        *TEXTUAL_DATAS,
        *SHERPA_DATAS,
    ],
    hiddenimports=[
        "sounddevice",
        *NATIVE_IMPORTS,
        *TEXTUAL_IMPORTS,
        *SHERPA_IMPORTS,
        # Heavy imports are deferred into subcommand handlers, so static
        # analysis from entry.py alone would miss most of the package.
        *collect_submodules("stenographer"),
    ],
    hookspath=[str(PROJECT_ROOT / "packaging")],
    runtime_hooks=(
        [str(PROJECT_ROOT / "packaging" / "rthooks" / "py_rth_portaudio.py")]
        if sys.platform == "linux" else []
    ),
    excludes=["PySide6", "stenographer_desktop"],
    noarchive=False,
)

# PyInstaller reclassifies the runtime's data files as binaries and copies the
# libraries they need into _internal/ a second time. They load from their own
# folder through RPATH, so drop those copies.
NEMO_RUNTIME_SRC = ASSET_SRC / NEMO_RUNTIME
a.binaries = [
    entry for entry in a.binaries
    if "/" in entry[0] or not Path(entry[1]).resolve().is_relative_to(NEMO_RUNTIME_SRC)
]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="stenographer",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="stenographer",
)
