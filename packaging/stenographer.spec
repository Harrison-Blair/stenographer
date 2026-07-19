# PyInstaller spec for stenographer.
#
# Build:  .venv/bin/pyinstaller packaging/stenographer.spec
# Output: dist/stenographer/stenographer  (--onedir)
#
# The bundled binary depends on these system libraries at runtime
# (not bundled because they are system-level):
#   - libevdev (for python-evdev)
#   - libportaudio (for sounddevice)
#   - gtk4-layer-shell (GTK4 support is collected by PyInstaller)
#   - libGL/Vulkan (for onnxruntime, on most distros)
# And these CLIs which are probed by `Capabilities.probe`:
#   - wtype, wl-copy, pw-play, paplay, evdev-readable keyboards
#
# The ASR model (~3 GB) is NOT bundled; it is downloaded by
# `stenographer model download` into the HuggingFace cache at
# first run.

# -*- mode: python ; coding: utf-8 -*-
import certifi
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets" / "sounds"
ICON_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets" / "icons"
FONT_SRC = PROJECT_ROOT / "src" / "stenographer" / "assets" / "fonts"

a = Analysis(
    [str(PROJECT_ROOT / "src" / "stenographer" / "cli.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[
        (str(ASSET_SRC), "stenographer/assets/sounds"),
        (str(ICON_SRC), "stenographer/assets/icons"),
        (str(FONT_SRC), "stenographer/assets/fonts"),
        (certifi.where(), "certifi"),
        *copy_metadata("stenographer"),
    ],
    hiddenimports=[
        "sounddevice",
        "evdev",
        "evdev._ecodes",
        "certifi",
        "argcomplete",
        "gi.repository.Gdk",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.Gtk",
        "gi.repository.Gtk4LayerShell",
        *collect_submodules("stenographer"),
    ],
    hookspath=[str(PROJECT_ROOT / "packaging")],
    hooksconfig={"gi": {"module-versions": {"Gtk": "4.0", "Gdk": "4.0"}}},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "rthooks" / "py_rth_portaudio.py")],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="stenographer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="stenographer",
)
