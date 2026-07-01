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
(`.github/workflows/release.yml`, see `spec/11-ci-release.md`) builds
them on every `workflow_dispatch` and attaches the tarball + SHA-256.

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

The total directory is currently ~370 MB on Linux x86_64. The largest
contributors are CTranslate2 (~60 MB) and ONNX Runtime (~55 MB).

## What the binary does NOT bundle

| Asset                                | How the user gets it                            |
|--------------------------------------|-------------------------------------------------|
| ASR model (`large-v3`, ~3 GB)        | `./dist/stenographer/stenographer model download` |
| System CLIs (`wtype`, `wl-copy`, `pw-play`, `paplay`) | Distro packages — see `spec/10-packaging.md` |
| System libraries (`libevdev`, `libportaudio`) | Distro packages                  |

## Runtime dependencies on the target machine

Install once on the target machine (Debian/Ubuntu names shown):

```sh
sudo apt install wtype wl-clipboard pipewire-audio libevdev1 libportaudio2
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

## Rebuilding

The build is fully reproducible from `packaging/stenographer.spec` and
`scripts/build.sh`. No manual steps are required beyond installing
`.[build]` and running the script.
