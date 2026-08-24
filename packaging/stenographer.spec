# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: F821 - Analysis/PYZ/EXE/COLLECT/SPECPATH are injected by PyInstaller
# PyInstaller spec for stenographer.
#
# Build: scripts/build.sh
# Direct: .venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec
# Output: dist/stenographer/stenographer  (onedir bundle)
#
# Deliberately NOT bundled — the target system must provide (see BUILD.md):
#   - libportaudio / pipewire / pulse libs (excluded by hook-sounddevice.py;
#     found at runtime via rthooks/py_rth_portaudio.py)
#   - wl-copy, canberra-gtk-play / pw-play / paplay CLIs; /dev/uinput access + `input` group
# The ASR model (~1.5 GB) is never bundled; `stenographer model download`
# fetches it into the HuggingFace cache (the only download path — hence certifi,
# which the daemon-start update notice's metadata request also uses when present).

# -*- mode: python ; coding: utf-8 -*-
from importlib.util import find_spec
from pathlib import Path

import certifi
from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets"
PYWAYLAND_FFI_SPEC = find_spec("pywayland._ffi")
if PYWAYLAND_FFI_SPEC is None or PYWAYLAND_FFI_SPEC.origin is None:
    raise RuntimeError("PyWayland CFFI extension is missing; reinstall pywayland==0.4.18")
PYWAYLAND_FFI = Path(PYWAYLAND_FFI_SPEC.origin)
PYWAYLAND_LIBRARIES = [
    (path, ".")
    for name, path in get_imports(PYWAYLAND_FFI)
    if path is not None and (name.startswith("libwayland-") or name.startswith("libffi."))
]

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    # Explicit collection keeps the completed PyWayland CFFI build and lets
    # PyInstaller trace its libwayland/libffi shared-library dependencies.
    binaries=[(str(PYWAYLAND_FFI), "pywayland"), *PYWAYLAND_LIBRARIES],
    datas=[
        # Sound cues plus the overlay quill, Caveat variable font, and OFL.
        (str(ASSET_SRC), "stenographer/assets"),
        (certifi.where(), "certifi"),
        # Silero VAD model — vad_filter is always on in model.py.
        *collect_data_files("faster_whisper", includes=["assets/*.onnx"]),
    ],
    hiddenimports=[
        "sounddevice",
        "evdev",
        "evdev._ecodes",
        "certifi",
        "pywayland._ffi",
        # Heavy imports are deferred into subcommand handlers, so static
        # analysis from entry.py alone would miss most of the package.
        *collect_submodules("stenographer"),
    ],
    hookspath=[str(PROJECT_ROOT / "packaging")],
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "rthooks" / "py_rth_portaudio.py")],
    excludes=[],
    noarchive=False,
)

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
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="stenographer",
)
