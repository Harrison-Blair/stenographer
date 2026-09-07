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
import os
import sys
from importlib.util import find_spec
from pathlib import Path

import certifi
from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets"
DESKTOP = os.environ.get("STENOGRAPHER_BUILD_HEADLESS") != "1"
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
    binaries=NATIVE_BINARIES,
    datas=[
        # Sound cues plus the overlay quill, Caveat variable font, and OFL.
        (str(ASSET_SRC), "stenographer/assets"),
        (certifi.where(), "certifi"),
        # Silero VAD model — vad_filter is always on in model.py.
        *collect_data_files("faster_whisper", includes=["assets/*.onnx"]),
    ],
    hiddenimports=[
        "sounddevice",
        "certifi",
        *NATIVE_IMPORTS,
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

executables = [exe]
binaries = list(a.binaries)
zipfiles = list(a.zipfiles)
datas = list(a.datas)
if DESKTOP:
    desktop = Analysis(
        [str(PROJECT_ROOT / "packaging" / "desktop_entry.py")],
        pathex=[str(PROJECT_ROOT / "src")],
        binaries=[],
        datas=[(str(ASSET_SRC), "stenographer/assets")],
        hiddenimports=collect_submodules("stenographer_desktop"),
        hookspath=[str(PROJECT_ROOT / "packaging")],
        excludes=[],
        noarchive=False,
    )
    desktop_pyz = PYZ(desktop.pure, desktop.zipped_data)
    desktop_exe = EXE(
        desktop_pyz, desktop.scripts, [], exclude_binaries=True,
        name="stenographer-ui", debug=False, strip=False, upx=False, console=False,
    )
    executables.append(desktop_exe)
    binaries.extend(desktop.binaries)
    zipfiles.extend(desktop.zipfiles)
    datas.extend(desktop.datas)

coll = COLLECT(
    *executables, binaries, zipfiles, datas,
    strip=False, upx=False, name="stenographer",
)
