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

- `workflow_dispatch` (manual run from the Actions tab). No inputs
  are required — the version is always read from `pyproject.toml`.

In v1 the workflow does **not** run on `push` to tags, on `push` to
branches, or on `pull_request`. The workflow file is structured so
that adding the tag trigger later is a one-line change to the `on:`
list:

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
`.github/workflows/build-release-draft.yml`.

### 1. `lint-test`

Runs on every manual workflow dispatch.

| Step | Command |
|---|---|
| Checkout | `actions/checkout@v7` |
| Set up Python | `actions/setup-python@v6` with `python-version-file: .python-version` |
| Install dev extras | `.venv/bin/pip install -e ".[dev]"` |
| Lint | `.venv/bin/ruff check .` |
| Format check | `.venv/bin/ruff format --check .` |
| Unit tests | `.venv/bin/pytest -m "not integration"` |

If any step exits non-zero the job fails and the workflow run is
marked failed. No artifacts are produced.

### 2. `build-release`

Runs on every manual workflow dispatch. The version is always read
from `pyproject.toml` — there is no manual input. The job fails if a
release for that version already exists.

| Step | Command / value |
|---|---|
| Checkout | `actions/checkout@v7` with `fetch-depth: 0` (needed for `git log` in the release notes) |
| Set up Python | `actions/setup-python@v6` with `python-version-file: .python-version` |
| Install system build deps | `sudo apt-get install -y wtype wl-clipboard pipewire-audio libevdev-dev libportaudio2` |
| Install build extras | `.venv/bin/pip install -e ".[dev,build]"` |
| Set VERSION | Reads `[project].version` from `pyproject.toml` via `tomllib` and exports `VERSION` to `$GITHUB_ENV` |
| Guard: release exists? | `gh release view "v${VERSION}"` — fails with an error if the release already exists |
| Build | `scripts/build.sh` |
| Package | `tar -C dist -czf stenographer-$VERSION-linux-x86_64.tar.gz stenographer/` |
| Hash | `sha256sum stenographer-$VERSION-linux-x86_64.tar.gz > stenographer-$VERSION-linux-x86_64.sha256` |
| Create draft release | `softprops/action-gh-release@v3` with `draft: true` |

The job matrix is `[ubuntu-latest]` in v1. aarch64 and macOS / Windows
builds are out of scope (see below).

### Pre-existing release guard

The `build-release` job reads `VERSION` from `pyproject.toml` early
(in a "Set VERSION" step that runs before any heavy build work) and
then checks whether a release with tag `v{VERSION}` already exists:

```sh
gh release view "v${VERSION}" &>/dev/null && {
  echo "::error::Release v${VERSION} already exists. Bump the version in pyproject.toml."
  exit 1
}
```

If the tag already has a GitHub Release (in any state — draft or
published), the job fails. The operator must bump the version in
`pyproject.toml` and re-trigger. This prevents accidental double
releases.

> The `gh` CLI is pre-installed on GitHub Actions runners. The job
> already has `contents: write` permission, which includes read access.

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

`softprops/action-gh-release@v3` accepts a `body:` parameter. The
workflow computes the body as:

```sh
if prev=$(git describe --tags --abbrev=0 "v${VERSION}^" 2>/dev/null); then
  git log "${prev}..v${VERSION}" --oneline
elif git describe --tags --abbrev=0 HEAD^ 2>/dev/null > prev_tag; then
  git log "$(cat prev_tag)..HEAD" --oneline
else
  git log --oneline
fi
```

This produces a flat list of commit subjects since the previous
tag. The project does not use Conventional Commits, so the spec does
not attempt to parse the messages.

### Draft releases

The workflow creates releases in **draft** state (`draft: true`).
A draft release is visible only to repo members with write access
and does not trigger webhook events (release notifications,
downstream workflows, watchers). The operator must review the
release on the GitHub Releases page and click **Publish release**
to make it public. This provides an additional human gate before
end users see the release.

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

The release job's pre-existing-release guard prevents creating a
release for a version that already exists; the operator must bump
the version in `pyproject.toml` and re-trigger.

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
