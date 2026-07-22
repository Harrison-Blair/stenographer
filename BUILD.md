<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Building a standalone binary

The project can be packaged as a self-contained Linux binary via PyInstaller.
The result needs no `pip install` and no Python on the target system (other
than the system libraries PyInstaller cannot bundle).

## Quick start

```sh
.venv/bin/pip install -e ".[build]"
scripts/build.sh
./dist/stenographer/stenographer --version
./dist/stenographer/stenographer doctor
```

## Prebuilt binaries

Prebuilt `dist/stenographer/` bundles (one per release) are attached
to the GitHub Releases for this repository. The release workflow
(`.github/workflows/release.yml`) builds them on every merge to `main` and
attaches the tarball + SHA-256, plus a self-bootstrapping `install.sh`.

The easiest way to consume a release is the installer, which downloads
the tarball, verifies its SHA-256, installs it, and sets up systemd +
config for you:

```sh
curl -fsSL https://github.com/Harrison-Blair/stenographer/releases/latest/download/install.sh | bash
```

To do it by hand instead:

```sh
VERSION=0.7.0
curl -L -o /tmp/stenographer.tar.gz \
  "https://github.com/Harrison-Blair/stenographer/releases/download/v${VERSION}/stenographer-${VERSION}-linux-x86_64.tar.gz"
curl -L -o /tmp/stenographer.tar.gz.sha256 \
  "https://github.com/Harrison-Blair/stenographer/releases/download/v${VERSION}/stenographer-${VERSION}-linux-x86_64.sha256"
cd /tmp && sha256sum -c stenographer.tar.gz.sha256
tar -xzf stenographer.tar.gz
mv stenographer /opt/
/opt/stenographer/stenographer --version
```

Or, if you have a previous build installed, just run
`./dist/stenographer/stenographer update`.

## Output

`dist/stenographer/stenographer` is a launcher script. The bundled payload
lives in `dist/stenographer/_internal/` (the Python interpreter, all
dependencies, and the six sound cues under
`_internal/stenographer/assets/sounds/`).

The total directory is currently ~510 MB on Linux x86_64. The largest
contributors include the GTK runtime, CTranslate2, and ONNX Runtime.

## What the binary does NOT bundle

| Asset                                | How the user gets it                            |
|--------------------------------------|-------------------------------------------------|
| ASR model (`whisper-medium.en`, ~1.5 GB) | `./dist/stenographer/stenographer model download` |
| System CLIs (`wtype`, `wl-copy`, `pw-play`, `paplay`, `notify-send`) | Distro packages — see the Requirements table in `README.md` |
| System libraries (`libevdev`, `libportaudio`, GTK4, `gtk4-layer-shell`) | Distro packages |

## Runtime dependencies on the target machine

Install once on the target machine (Debian/Ubuntu names shown):

```sh
sudo apt install wtype wl-clipboard pipewire-audio libevdev1 libportaudio2 \
  libnotify-bin libgtk-4-1 libgtk4-layer-shell0 gir1.2-freedesktop \
  gir1.2-gtk4layershell-1.0
sudo usermod -aG input $USER   # log out / back in for this to take effect
```

The user must be in the `input` group for the hotkey to be capturable.

## systemd integration with the binary

Replace the `ExecStart` line in
`packaging/stenographer.service.in` with:

```ini
ExecStart=/opt/stenographer/stenographer run
```

(or wherever the user copies `dist/stenographer/`).

## Development workflow

Develop features on the `dev` branch. Merging `dev` → `main` triggers
`.github/workflows/release.yml`, which lints, tests, builds the binary, and
**publishes** a `v<version>` GitHub release. Because the workflow refuses to
reuse an existing release, **every merge to `main` must bump
`__version__` in `src/stenographer/_version.py`.** Source and local builds use
the `<version>-dev` form; the release workflow validates and strips that suffix
in its temporary checkout before building the published binary.

Set up the git hooks once after cloning:

```sh
./scripts/install-hooks.sh
```

This points `core.hooksPath` at `.githooks/`, whose `pre-commit` hook runs
`ruff format` on staged Python files and re-stages them — so commits are always
formatted and CI's `ruff format --check` never fails on your work.

## Rebuilding

The build is fully reproducible from `packaging/stenographer.spec` and
`scripts/build.sh`. No manual steps are required beyond installing
`.[build]` and running the script.
