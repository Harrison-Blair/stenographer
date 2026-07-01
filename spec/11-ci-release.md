<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 11 — CI release workflow

## Dependencies

- **Reads:** `00-overview.md` (components, lifecycle).
- **Reads:** `07-configuration.md` (`update.*` keys, `__version__` source).
- **Reads:** `10-packaging.md` (PyInstaller layout, system build deps, `dist/stenographer/`).
- **This is the LAST spec to implement for the CI workflow itself.** The
  build scripts and the workflow YAML may exist independently of the
  `update` subcommand (CI is useful even if no client ever self-updates).

## Goal

Define a GitHub Actions workflow that produces a release-quality
PyInstaller `--onedir` binary, validates the release tag against the
project's declared version, attaches the binary to a GitHub Release,
and runs the project's lint and unit-test suite on every push and
pull request.

## Trigger

The workflow runs on:

- `workflow_dispatch` (manual run from the Actions tab).

In v1 the workflow does **not** run on `push` to tags, on `push` to
branches, or on `pull_request`. The operator wants to exercise the
release end-to-end before turning on automatic triggers. The
workflow file is structured so that adding the tag trigger later
is a one-line change to the `on:` list:

```yaml
on:
  workflow_dispatch:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+*"
```

> Follow-up (separate spec doc, see `13-asset-retention.md`): a
> concurrent-eligible subagent can add a tag-triggered job and a
> release-asset retention policy.

## Jobs

The workflow file contains two jobs. Both are defined in
`.github/workflows/release.yml`.

### 1. `lint-test`

Runs on every manual workflow dispatch.

| Step | Command |
|---|---|
| Checkout | `actions/checkout@v4` |
| Set up Python | `actions/setup-python@v5` with `python-version-file: .python-version` |
| Install dev extras | `.venv/bin/pip install -e ".[dev]"` |
| Lint | `.venv/bin/ruff check .` |
| Format check | `.venv/bin/ruff format --check .` |
| Unit tests | `.venv/bin/pytest -m "not integration"` |

If any step exits non-zero the job fails and the workflow run is
marked failed. No artifacts are produced.

### 2. `build-release`

Runs on every manual workflow dispatch. The job expects the operator
to know the version they are about to release; the tag ↔ version
validation step below uses `github.ref_name` only when triggered by
a tag push (which is currently disabled).

| Step | Command / value |
|---|---|
| Checkout | `actions/checkout@v4` with `fetch-depth: 0` (needed for `git log` in the release notes) |
| Set up Python | `actions/setup-python@v5` with `python-version-file: .python-version` |
| Install build extras | `.venv/bin/pip install -e ".[dev,build]"` |
| Install system build deps | `sudo apt-get install -y wtype wl-clipboard pipewire-audio libevdev-dev libportaudio2` |
| Build | `scripts/build.sh` |
| Package | `tar -C dist -czf stenographer-$VERSION-linux-x86_64.tar.gz stenographer/` |
| Hash | `sha256sum stenographer-$VERSION-linux-x86_64.tar.gz > stenographer-$VERSION-linux-x86_64.sha256` |
| Create / update release | `softprops/action-gh-release@v2` |

The job matrix is `[ubuntu-latest]` in v1. aarch64 and macOS / Windows
builds are out of scope (see below).

> **Tag ↔ version validation is currently disabled** because the
> workflow only runs on `workflow_dispatch` (no tag is associated
> with the run). When the tag trigger is added in a follow-up, the
> validation step in the workflow file is re-enabled and the
> contract below applies.

### Tag ↔ version validation

The release job compares the pushed tag against the version in
`pyproject.toml`. For a tag `vX.Y.Z[-suffix]`:

1. Strip the leading `v`.
2. Split on the first `-` to separate the numeric portion
   `X.Y.Z` from the optional pre-release suffix.
3. The numeric portion must match `pyproject.toml`'s
   `[project].version` **exactly** (character-for-character). If it
   does not, the job fails with a precise error message:

   ```
   tag v0.7.0 does not match pyproject.toml [project].version = 0.6.0.
   Bump the version in pyproject.toml or push a different tag.
   ```

Pre-release tags like `v0.7.0-rc.1` are accepted; the numeric
portion (`0.7.0`) is what must match. The pre-release suffix is
free-form and is preserved as the GitHub Release tag verbatim.

### Release assets

The job attaches the following to the GitHub Release:

- `stenographer-$VERSION-linux-x86_64.tar.gz` — the PyInstaller
  `--onedir` payload at `dist/stenographer/`. Size is approximately
  370 MB (CTranslate2 + ONNX Runtime dominate).
- `stenographer-$VERSION-linux-x86_64.sha256` — SHA-256 of the
  tarball, in `sha256sum`-compatible format.

The tarball layout:

```
stenographer/
├── stenographer          # launcher
└── _internal/            # Python interpreter, dependencies, assets
    └── stenographer/
        └── assets/
            ├── sounds/   # ptt_on.wav, ptt_off.wav, ...
            └── icons/    # stenographer.png
```

### Release body

`softprops/action-gh-release@v2` accepts a `body:` parameter. The
workflow computes the body as:

```sh
git log $(git describe --tags --abbrev=0 HEAD^)..HEAD --oneline
```

with a fallback for the first release:

```sh
git log --oneline
```

This produces a flat list of commit subjects since the previous
tag. The project does not use Conventional Commits, so the spec does
not attempt to parse the messages.

## Versioning contract

`pyproject.toml`'s `[project].version` is the **single source of
truth** for the version string. The Python package's
`__version__` is derived from it at runtime:

```python
# src/stenographer/__init__.py
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("stenographer")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
```

This means:

- Editing `pyproject.toml` and reinstalling (`pip install -e .`)
  propagates the new version to `__version__` without touching any
  Python source.
- The PyInstaller bundle embeds whatever `importlib.metadata.version`
  returns from the build venv — which is the pyproject value — so
  the `update` command's `__version__` inside the binary matches
  the release tag.
- Editing `__version__` directly is no longer possible; the
  comment in `__init__.py` should call this out.

The release job's tag-validation step enforces that the tag matches
pyproject; mismatches fail the build.

## System build dependencies (CI only)

The CI runner needs these **at build time**:

| Debian / Ubuntu package | Why at build time |
|---|---|
| `wtype` | runtime probe in `Capabilities.probe`; CI runs `doctor` to verify the bundle works. |
| `wl-clipboard` | same as above. |
| `pipewire-audio` | provides `pw-play` and the PortAudio shim used by `sounddevice`. |
| `libevdev-dev` | the `evdev` wheel on Python 3.14 is a source build; without headers the install step fails. |
| `libportaudio2` | runtime for `sounddevice`; CI needs it to verify the bundle's mic probe. |

These are **not** bundled in the binary; the runtime-system-package
list in `spec/10-packaging.md` already requires the same packages on
the target machine.

## Out of scope (v1)

- aarch64 runner (`ubuntu-24.04-arm`).
- Code signing (GPG, cosign).
- SBOM generation.
- PyPI publish (separate workflow, separate spec).
- Tag-based automatic trigger (see "Trigger" above; added in a
  follow-up).
- Release-asset retention policy. A separate spec doc
  (`13-asset-retention.md`) is the spec for the follow-up; the
  subagent implementing it can run in parallel with the `update`
  subcommand work.

## Open questions

- **Build cache.** PyInstaller's analysis step is slow (~5 min on
  ubuntu-latest). A `pyinstaller` cache (`--cache-dir`) keyed on
  the spec file hash would help, but v1 skips it for simplicity.
- **Cross-arch pip wheels.** Some heavy dependencies
  (`faster-whisper`, `onnxruntime`) have aarch64 wheels on PyPI; a
  follow-up can add an `ubuntu-24.04-arm` runner and produce
  matching assets. Out of scope for v1.
