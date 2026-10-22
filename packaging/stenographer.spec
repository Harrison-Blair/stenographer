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
# The ASR and live voice models are never bundled; explicit `stenographer
# model download` commands fetch them into local model directories. Certifi is
# optional; the update notice uses it when installed, or the system trust store.

# -*- mode: python ; coding: utf-8 -*-
import sys
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.depend.bindepend import get_imports
from PyInstaller.utils.hooks import collect_all, collect_submodules

try:
    import certifi
except ImportError:
    CERTIFI_DATAS = []
    CERTIFI_IMPORTS = []
else:
    CERTIFI_DATAS = [(certifi.where(), "certifi")]
    CERTIFI_IMPORTS = ["certifi"]

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets"
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
        (str(ASSET_SRC), "stenographer/assets"),
        *CERTIFI_DATAS,
        *TEXTUAL_DATAS,
        *SHERPA_DATAS,
    ],
    hiddenimports=[
        "sounddevice",
        *CERTIFI_IMPORTS,
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
