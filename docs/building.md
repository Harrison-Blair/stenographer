<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Building a standalone bundle

This is contributor and release documentation. For installation and everyday
use, see the [README](../README.md) and [user guide](usage.md).

A local PyInstaller onedir build for machines without a Python setup, plus a
limited release channel for Linux x86_64 and AArch64. Scope remains
deliberately narrow: no multi-distro installer or self-update. The included
installer targets one machine and one user only.

## Release notes

Stable `vX.Y.Z` Git tags are the sole release-version authority; there is no
source version to bump. GitHub generates each release's notes from the titles of
the pull requests merged since the previous release, so a clear PR title is the
release note. The notes of earlier releases stay on GitHub.

## Quick start

```sh
python3 -m venv .venv                      # if not already present
.venv/bin/pip install -e ".[dev,build]"
scripts/build.sh
dist/stenographer/stenographer --version
```

## Repository and distribution contents

The repository ignores files by default. `.gitignore` allows Python code in
the application and tests, development scripts, packaging files, workflows,
and explicitly listed metadata, documentation, and bundled assets. Local
recordings, downloaded models, caches, build output, and agent/editor settings
stay ignored. Shared guidance remains in `AGENTS.md` and `CLAUDE.md`.
PyInstaller collects only the
application entry point, modules, and assets.

For a new file type, documentation file, or asset, update both `.gitignore`
and `[tool.hatch.build].exclude` in `pyproject.toml` before staging it. Keep
their non-comment patterns identical and in the same order, including the
parent-directory exceptions. Existing Python and script patterns allow new
modules automatically. Use `git check-ignore -v --no-index <path>` to inspect
which rule applies; review `git status --short` before staging. Ignore rules
do not remove tracked files or prevent an explicit `git add -f`.

Hatchling can discard VCS exclusions when the catch-all pattern matches the
project root. Builds therefore set `ignore-vcs = true` and apply the mirrored
exclusions explicitly. The final recursive content rules also prevent local
files from entering packages when a builder traverses an ignored directory.
After changing the policy, build and verify the wheel and source distribution
with `scripts/verify_distributions.py`, check archive contents, and verify that
the source distribution can build a wheel. Preserve the source distribution's
installer scripts and all required package resources. The Agent rewrite
prompt's MIT attribution is packaged at
`stenographer/assets/licenses/asd-ste100-MIT.txt` in wheels and retained under
`src/` in source distributions. The model attribution files
(`underdog-bark-3.0-pro-NOTICE.txt`, `silero-vad-MIT.txt`,
`wespeaker-resnet34-LM-NOTICE.txt`, `pyannote-segmentation-3.0-MIT.txt`, and
`nemotron-3-diarization-OpenMDW-1.1-NOTICE.txt`) and the NeMo-Speech.cpp notices
(`nemo-speech/`) sit in the same folder, as do the Bark Pro converter and its venv lock under
`stenographer/assets/convert/`. Three models ship with the app and are committed
to Git in `stenographer/assets/models/`:

| File | Size | SHA-256 |
| --- | --- | --- |
| `pyannote-segmentation-3-0.onnx` | about 6 MB | `220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079` |
| `silero_vad.onnx` | about 0.6 MB | `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` |
| `wespeaker_en_voxceleb_resnet34_LM_mean.onnx` | about 27 MB | `280d78ccc3a8a3ffdf4d9ef867e16faa68d2beb107ad1de7a844285d3522fcd6` |

`silero_vad.onnx` is unchanged from the
[sherpa-onnx release](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx).
The ASR model is an explicit download.

### Speaker separation runtime

Speaker separation uses NVIDIA Nemotron-3-Diarization, run by the native
NeMo-Speech.cpp 0.3.0 runtime through its C API in a helper process.

- **Runtime libraries** are committed to Git in
  `stenographer/assets/nemo_speech/linux-x86_64/` and `linux-aarch64/`: the 12
  files that the C library loads, from the release's Linux CPU tarballs.
  `nemo_speech/SOURCES.txt` records the tarball and file SHA-256 values. Every
  library has RPATH `$ORIGIN`, so each folder loads as a unit. The x86_64 build
  needs an AVX2 CPU; without one the app records and transcribes with no
  speaker labels.
- **The speaker model** (`Nemotron-3-Diarization.q8_0.gguf`, 107,012,128
  bytes, SHA-256 `08456d9e22cd9a323c0364d98375f3746d6e68507ebb705cd46438c534c7a3a1`)
  is larger than GitHub's file limit and is never committed. `scripts/build.sh`
  runs `scripts/fetch_speaker_model.py`, which downloads it from the pinned
  Hugging Face revision into `src/stenographer/assets/models/` (git-ignored).
  A file with the pinned size and SHA-256 is kept, so a rebuild does not
  download again; any mismatch fails the build. Run the script by hand to use
  speaker separation from a source checkout.
- **The bundle** ships the model and the libraries of the build architecture
  only, once, under `_internal/stenographer/assets/`. The wheel and source
  distribution carry the libraries of both architectures but not the model.

### Speaker model

The bundled speaker model is the sherpa-onnx export of WeSpeaker ResNet34-LM
with mean subtraction added to the start of the ONNX graph: the model expects
features with their mean over time subtracted, and sherpa-onnx does not do that
step. `scripts/speaker_model_mean.py` makes the file. It needs the `onnx`
package (tested with 1.23.2), which is not an app dependency:

```sh
python3 -m venv /tmp/onnx-venv && /tmp/onnx-venv/bin/pip install onnx==1.23.2
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx
/tmp/onnx-venv/bin/python -I scripts/speaker_model_mean.py \
  wespeaker_en_voxceleb_resnet34_LM.onnx wespeaker_en_voxceleb_resnet34_LM_mean.onnx
```

The script checks the sha256 of the source and prints the sha256 of the output,
which must match the table above.

## Releases

Test on a real machine first; see
[native acceptance requirements](../packaging/NATIVE-ACCEPTANCE.md). One manual
workflow run on `main` then publishes the release directly:

```sh
gh workflow run release.yml --ref main -f bump=minor
```

The `bump` input is `patch`, `minor`, or `major`. The workflow calculates `X.Y.Z`
from the highest stable `vX.Y.Z` tag. After lint, non-integration tests, and both
native standalone builds pass, it creates a GitHub draft with generated notes,
uploads every asset, checks that the draft has these six assets, and publishes
it:

- `stenographer-X.Y.Z-linux-x86_64.tar.gz`
- `stenographer-X.Y.Z-linux-aarch64.tar.gz`
- `stenographer-X.Y.Z-py3-none-any.whl`
- `stenographer-X.Y.Z.tar.gz`
- `SHA256SUMS`
- `quick-install.sh`

Each standalone archive contains the complete onedir bundle and `LICENSE`.
The workflow checks every SHA-256 entry and records signed provenance for all
six files. `SHA256SUMS` lists the four archives, not `quick-install.sh`. The
draft stage exists so that a user never sees a release with missing files, and
so that a run that failed before publishing can be retried.

Publishing then starts the `pages` workflow, because a release published with
the workflow token does not trigger other workflows. It builds the site from the
new tag and serves the release's `quick-install.sh` as `install.sh`. If the
release is published but the site did not deploy, start the deploy by hand:

```sh
gh workflow run pages.yml --ref main -f ref=vX.Y.Z
```

A manual `pages` run with no `ref` builds `main`. Either way it downloads
`install.sh` from the latest release, and fails if the download fails.

Never rerun a release that is already published, even if its run failed: a rerun
of failed jobs stops at the guard, and a rerun of all jobs or a new run publishes
the next version from the same commit.

The planner reads the complete Git tag history, rejects malformed `v` tags,
requires every published GitHub release to retain its stable tag, refuses an
existing candidate tag, and rechecks the chosen predecessor tag and commit
before attestation and before changing the draft. A single matching draft is
refreshed only when it already targets the dispatch commit, so a run that failed
before publishing can be retried from the same commit with the same bump; a
refresh leaves the draft's notes alone.
Unrelated, foreign-commit, or duplicate drafts fail closed. A draft left by a
failed run therefore blocks a release from a newer commit until the draft is
deleted.

A published bad release is fixed by a new patch release. Tags never move:
configure the repository to prevent deletion or force-updates of release tags.

`src/stenographer/_version.py` is generated build metadata rather than a
release input. In an ordinary source or editable checkout it reports the
explicit non-release version `0.0.0+source`. Each release build generates the
tag-derived version before installing, freezing, or packaging the application,
so wheel, source distribution, standalone bundle, and `--version` agree. The
manual `release preflight` workflow can rehearse a selected bump without
creating a tag or release; pull-request runs use a patch candidate only to
exercise packaging.
The guard requires either `--target-commit` or an explicit opt-out, so a
dropped flag fails instead of silently skipping a check:

- The release workflow passes `--target-commit` on every guard call.
- A manual rehearsal on `main` passes `--target-commit` too.
- A manual rehearsal on another branch passes `--skip-target-check`: it still
  rejects unrelated or duplicate drafts, but a draft targeting `main` cannot
  match that branch's commit.
- A pull-request run passes `--skip-draft-checks`: it runs on a temporary merge
  commit and would plan a patch even while a failed run's minor or major draft
  remains, so it ignores drafts and plans its version from tags only.

The README's one-line installer, `scripts/quick-install.sh`, consumes that
published release: it downloads the native standalone archive, the source
distribution, and `SHA256SUMS`, verifies both archives, and runs the source
distribution's `scripts/install.sh` on the prebuilt bundle. Renaming any of
those assets breaks it. It installs, updates, and repairs with the same command,
always reinstalling, and keeps the service state: a running service restarts on
the new version, a stopped service stays stopped, and a disabled service stays
disabled. A new install is enabled and stays stopped.

The native ARM runner validates packaging, executable architecture, `--version`,
and `--help`; it cannot validate Wayland, microphone, or uinput behavior. Before
starting the first AArch64 release, run `doctor` and real dictation on an
AArch64 Wayland machine.

PyWayland 0.4.18 normally installs from a wheel. If no wheel exists for the
host Python/architecture, installing the source package also needs a C compiler,
Python development headers, Wayland client/server development headers, and
libffi development headers (for example `build-essential`, `python3-dev`,
`libwayland-dev`, and `libffi-dev` on Debian-family systems). These are build
requirements only; the onedir bundle contains the completed CFFI extension.

`scripts/build.sh` and `scripts/install.sh` show elapsed time in animated
progress bars, with the last three log lines beneath them. The installer also
shows the current phase. Both deliberately
omit an overall percentage and ETA because their underlying tools expose no
reliable total work estimate. Full tool output goes to `dist/build.log` /
`dist/install.log` (dumped on failure); pass `--verbose` to stream the raw
output instead.

If overlay backend imports fail in a source installation, force a fresh build
and immediately install it by running:

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
scanner. The xdg-output binding comes from PyWayland itself and is not generated
in the source tree. The private helper re-exec entry remains intentionally absent from
public `--help` output.

`scripts/build.sh` rejects a source or frozen tree unless it contains exactly
those four pack directories and exactly the four lifecycle cues in each. The
release workflow applies the same fail-closed guard to the wheel, source
distribution, frozen bundle, and final standalone archives. The three new packs
are original deterministic procedural renders from the checked-in
`scripts/cue_audition.py`; verify their packaged bytes with:

```sh
.venv/bin/python scripts/cue_audition.py --verify-packaged
```

See [cue-audition.md](cue-audition.md) for generation provenance and
the required listening checks.

## Deliberately not bundled

The target system must provide:

- **libportaudio** (e.g. the `libportaudio2` package) — excluded from the
  bundle by `packaging/hook-sounddevice.py` so the system audio stack is
  used; found at runtime via `packaging/rthooks/py_rth_portaudio.py`.
- **`wl-copy`** (wl-clipboard) — clipboard delivery with Wayland data control;
  **`xclip`** provides the X11/XWayland fallback.
- **`canberra-gtk-play`, `pw-play`, or `paplay`** — audio cues, in preference
  order (degrades to silent if absent).
- **`/dev/uinput` write access** and membership in the **`input` group** —
  paste chord and hotkey capture.
- **The ASR model** — never bundled. Build it once with
  `dist/stenographer/stenographer model download --asr` (about 1.6 GB
  download, 10 GiB free disk, about 10.2 GiB RAM, CPU only). The build needs
  `python3-venv` (`sudo apt install python3-venv`) for its temporary
  converter venv.

`dist/stenographer/stenographer doctor` reports exactly what is missing
(exit 78 when a required capability is absent).

## Native development builds

All installations contain the `stenographer` CLI/daemon and its existing
helpers. Qt and the settings GUI are no longer packaged. Install dependencies
with `.venv/bin/pip install -e '.[dev,build]'`, then run `scripts/build.sh`.
`--headless` remains accepted by `build.sh`, `install.sh`, and `reinstall.sh`
as a compatibility no-op.

The Linux installer rebuilds an existing bundle containing the old GUI before
installing. It removes an obsolete `stenographer-ui` symlink only when it points
to this installation, and separately removes the old menu entry only when its
launch command points to this installation's GUI. Existing configuration,
analytics history, models, and logs (including `desktop.log`) are preserved.
Use `stenographer setup` and `stenographer sounds` for configuration and
`stenographer stats` for numeric diagnostics; restart the daemon explicitly to
apply saved settings.

The native CI workflow builds a relocatable development bundle for Linux x86_64.
It runs the non-integration suite and frozen CLI checks. The artifact includes
`LICENSE` and `NATIVE-ACCEPTANCE.md`. Copy and run the complete bundle directory.
Linux release bundles continue through their source distribution's installer.

Interactive installation, audio, keyboard, clipboard, service, and helper
isolation checks remain separate gates. Automated checks do not capture
microphone audio. See [native acceptance requirements](../packaging/NATIVE-ACCEPTANCE.md).
