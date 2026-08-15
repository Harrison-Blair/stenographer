<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Building a standalone bundle

A local PyInstaller onedir build for machines without a Python setup.
Scope is deliberately narrow: no release CI, multi-distro installer, or
self-update (see `docs/reauthor.md` §7). The included installer targets one
machine and one user only.

## Quick start

```sh
python3 -m venv .venv                      # if not already present
.venv/bin/pip install -e ".[dev,build]"
scripts/build.sh
dist/stenographer/stenographer --version
```

PyWayland 0.4.18 normally installs from a wheel. If no wheel exists for the
host Python/architecture, installing the source package also needs a C compiler,
Python development headers, Wayland client/server development headers, and
libffi development headers (for example `build-essential`, `python3-dev`,
`libwayland-dev`, and `libffi-dev` on Debian-family systems). These are build
requirements only; the onedir bundle contains the completed CFFI extension.

`scripts/build.sh` and `scripts/install.sh` show a progress bar and write full
tool output to `dist/build.log` / `dist/install.log` (dumped on failure).
Pass `--verbose` to stream the raw output instead.

To force a fresh build and immediately install it, run:

```sh
scripts/reinstall.sh
```

Installer options are forwarded to `scripts/install.sh`; `--verbose` applies
to both stages.

## What you get

An onedir bundle at `dist/stenographer/` — the `stenographer` binary plus an
`_internal/` tree. It is relocatable as a directory: copy the whole thing
anywhere and symlink the binary onto your `PATH`. Do not extract single files
out of it.

The bundle includes the lifecycle icon, Caveat font and OFL license, generated
layer-shell/fractional-scale/viewporter Python bindings, Pillow, python-xlib,
and the completed PyWayland CFFI extension with its collected shared-library
requirements. Protocol bindings are generated in the source tree before
building; neither installed source packages nor frozen helpers run a protocol
scanner. The private helper re-exec entry remains intentionally absent from
public `--help` output.

## Deliberately not bundled

The target system must provide:

- **libportaudio** (e.g. the `libportaudio2` package) — excluded from the
  bundle by `packaging/hook-sounddevice.py` so the system audio stack is
  used; found at runtime via `packaging/rthooks/py_rth_portaudio.py`.
- **`wl-copy`** (wl-clipboard) — clipboard delivery.
- **`canberra-gtk-play`, `pw-play`, or `paplay`** — audio cues, in preference
  order (degrades to silent if absent).
- **`/dev/uinput` write access** and membership in the **`input` group** —
  paste chord and hotkey capture.
- **The ASR model** (~1.5 GB) — never bundled. Fetch it once with
  `dist/stenographer/stenographer model download` (the only network path;
  `certifi` is bundled for exactly this).

`dist/stenographer/stenographer doctor` reports exactly what is missing
(exit 78 when a required capability is absent).
