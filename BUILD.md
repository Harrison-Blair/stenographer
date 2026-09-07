<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Building a standalone bundle

A local PyInstaller onedir build for machines without a Python setup, plus a
limited draft-release channel for Linux x86_64 and AArch64. Scope remains
deliberately narrow: no multi-distro installer or self-update (see
`AGENTS.md`). The included installer targets one machine and one user
only.

## Quick start

```sh
python3 -m venv .venv                      # if not already present
.venv/bin/pip install -e ".[dev,build]"
scripts/build.sh
dist/stenographer/stenographer --version
```

## Draft releases

A push to `main`, or a manual workflow dispatch targeting `main`, creates or
refreshes an unpublished GitHub draft for the checked-in `X.Y.Z` version. It
does so only after lint, non-integration tests, and both native standalone
builds pass. The draft contains:

- `stenographer-X.Y.Z-linux-x86_64.tar.gz`
- `stenographer-X.Y.Z-linux-aarch64.tar.gz`
- `stenographer-X.Y.Z-py3-none-any.whl`
- `stenographer-X.Y.Z.tar.gz`
- `SHA256SUMS`

Each standalone archive contains the complete onedir bundle and `LICENSE`.
The workflow checks every SHA-256 entry and records signed provenance for all
five files. It never publishes a release: publishing the reviewed draft
manually creates the stable `vX.Y.Z` release.

The README's one-line installer, `scripts/quick-install.sh`, consumes that
published release: it downloads the native standalone archive, the source
distribution, and `SHA256SUMS`, verifies both archives, and runs the source
distribution's `scripts/install.sh` on the prebuilt bundle. Renaming any of
those assets breaks it.

The native ARM runner validates packaging, executable architecture, `--version`,
and `--help`; it cannot validate Wayland, microphone, or uinput behavior. Before
publishing the first AArch64 release, run `doctor` and real dictation on an
AArch64 Wayland machine.

PyWayland 0.4.18 normally installs from a wheel. If no wheel exists for the
host Python/architecture, installing the source package also needs a C compiler,
Python development headers, Wayland client/server development headers, and
libffi development headers (for example `build-essential`, `python3-dev`,
`libwayland-dev`, and `libffi-dev` on Debian-family systems). These are build
requirements only; the onedir bundle contains the completed CFFI extension.

`scripts/build.sh` and `scripts/install.sh` show elapsed time and the current
phase in animated progress bars, with the last three log lines beneath them.
The build also shows measured hook and hidden-import counts. Both deliberately
omit an overall percentage and ETA because their underlying tools expose no
reliable total work estimate. Full tool output goes to `dist/build.log` /
`dist/install.log` (dumped on failure); pass `--verbose` to stream the raw
output instead.

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

The bundle includes the lifecycle icon, Caveat font and OFL license, native
Bash/Zsh/Fish completion definitions, all 16 WAVs from the four nested bundled
sound packs (`legacy`, `warm-desk`, `soft-electronic`, `minimal-ui`), generated
layer-shell/fractional-scale/viewporter Python bindings, Pillow, python-xlib,
and the completed PyWayland CFFI extension with its collected shared-library
requirements. Protocol bindings are generated in the source tree before
building; neither installed source packages nor frozen helpers run a protocol
scanner. The private helper re-exec entry remains intentionally absent from
public `--help` output.

`scripts/build.sh` rejects a source or frozen tree unless it contains exactly
those four pack directories and exactly the four lifecycle cues in each. The
draft-release workflow applies the same fail-closed guard to the wheel, source
distribution, frozen bundle, and final standalone archives. The three new packs
are original deterministic procedural renders from the checked-in
`scripts/cue_audition.py`; verify their packaged bytes with:

```sh
.venv/bin/python scripts/cue_audition.py --verify-packaged
```

See [docs/cue-audition.md](docs/cue-audition.md) for generation provenance and
the required listening checks.

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

## Desktop and headless installations

The normal native bundle now contains two independent executables:
`stenographer` (CLI/daemon) and `stenographer-ui` (PySide6 Widgets). Install build
dependencies with `.venv/bin/pip install -e '.[dev,build,desktop]'`, then run
`scripts/build.sh`. Each executable has its own Python module archive; the CLI
archive excludes Qt and the desktop package. Closing the desktop leaves the
daemon running. Linux `scripts/install.sh` installs both launchers and a desktop
menu entry. The desktop uses its own `desktop.log` in the application state
directory.

For a Qt-free installation, install the Python package without the `desktop`
extra, or use `scripts/build.sh --headless` and `scripts/install.sh --headless`.
`scripts/reinstall.sh --headless` forwards the choice to both steps.
An existing desktop bundle is rebuilt for `--headless` so it does not retain Qt
libraries. The desktop extra is optional on the Python distribution; one wheel
contains both import-isolated packages and launchers.

`.github/workflows/desktop.yml` builds native development artifacts for Linux
x86_64, Windows x86_64, macOS Intel, and macOS Apple Silicon, using the
[documented native GitHub runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
It runs the pure/native
transport/database suites, and launches the GUI offscreen without a daemon.
The artifacts include `install-native.py`, a per-user Windows/macOS development
installer, and `NATIVE-ACCEPTANCE.md`. Invoke that installer with a Python 3.12+
environment and the unpacked bundle (or use `--bundle PATH`). It creates a
Windows Start Menu shortcut or a macOS application bundle; it does not create
unsupported dictation services. Linux release bundles continue through their
source distribution's installer.

These Windows/macOS artifacts are **unsigned development builds, not accepted
release packages**. Native dictation providers remain unavailable on those
hosts. Interactive installation, accessibility, scaling, audio, keyboard,
clipboard, and service checks remain separate gates. macOS signing/notarization
and Windows signing/installation checks must pass before release readiness is
claimed. Offscreen checks never capture microphone audio.
