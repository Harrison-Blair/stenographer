<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 12 — Self-update subcommand

## Dependencies

- **Reads:** `00-overview.md` (lifecycle, capabilities).
- **Reads:** `07-configuration.md` (`update.*` keys).
- **Reads:** `08-process-model.md` (CLI surface, exit codes, lock file).
- **Reads:** `09-error-handling.md` (degradation policy, errors module).
- **Reads:** `10-packaging.md` (PyInstaller `--onedir` layout).
- **Reads:** `11-ci-release.md` (release asset format, tag format).
- **Blocks:** nothing; the `update` subcommand is a leaf component.

## Goal

Provide a `stenographer update` subcommand that:

1. Queries the project's GitHub Releases API for the latest stable
   release.
2. Compares it against the running binary's `__version__`.
3. If newer, prompts the user, downloads the release tarball, verifies
   its SHA-256, and replaces the running binary in place.
4. Stops the running daemon (via the systemd user service) before the
   swap and starts it again afterwards.
5. Reports success or a precise error.

The subcommand is **interactive by default** (a `y/N` prompt) and
**non-interactive with `--yes`**.

## CLI surface

```
stenographer update [--check] [--yes] [--no-restart] [--prerelease]
                    [--repo OWNER/NAME]
```

| Flag | Default | Meaning |
|---|---|---|
| `--check` | off | Print whether an update is available. Do not download, do not restart. Exit 0 in both "up to date" and "update available" cases. |
| `--yes` | off | Skip the confirmation prompt. |
| `--no-restart` | off | Do not call `systemctl --user start` after the swap. Implies the user will start the daemon themselves. The stop step still runs. |
| `--prerelease` | off | Include pre-release tags (e.g. `v0.7.0-rc.1`) in the candidate set. Overrides `update.channel` for this invocation. |
| `--repo OWNER/NAME` | `cfg.update.repo` | Override the configured GitHub repository for this invocation. |

The subcommand is registered alongside the existing subcommands in
`spec/08-process-model.md`'s CLI surface.

## Update transport

GitHub Releases API at `{update.base_url}/repos/{update.repo}/releases`.

- The candidate set is the most recent `per_page=10` releases.
- The CLI picks the highest version per `update.channel` (see below),
  using `packaging.version.Version` for ordering.
- The chosen release's `assets` array is searched for an entry whose
  `name` matches `update.asset_pattern` with `{version}` substituted
  by the chosen version (e.g.
  `stenographer-0.7.0-linux-x86_64.tar.gz`).
- A matching `*.sha256` file is expected in the same release's
  assets (e.g. `stenographer-0.7.0-linux-x86_64.sha256`). Its
  presence is required; absence → exit 1.

The API is hit unauthenticated. The unauthenticated rate limit is
60 requests / hour / IP. `update` makes at most two requests per
run (one for the release list, one for the tarball download via
the asset's `browser_download_url`); well within the budget.

## Default flow

1. **Resolve current version** from `__version__` (see
   `spec/11-ci-release.md` "Versioning contract").

2. **Fetch the candidate releases** with
   `GET {base_url}/repos/{repo}/releases?per_page=10`. Parse each
   release's `tag_name`, strip the leading `v`, parse as
   `packaging.version.Version`.

3. **Filter by channel**:
   - `update.channel = "stable"` (default) → drop releases whose
     `prerelease` flag is `true` (set by GitHub for tags matching
     the pre-release pattern).
   - `update.channel = "latest"` → keep all releases.
   - The `--prerelease` CLI flag forces `"latest"` for this
     invocation.

4. **Pick the highest version** from the filtered set. If the
   filtered set is empty, exit 1 with a precise error.

5. **Compare** to `__version__`. If `latest <= current`, print
   `up to date: <version>` and exit 0. Otherwise, print
   `update available: <current> -> <latest>` to stderr and
   continue. If `--check`, do not download and do not restart.

6. **Display the change log.** Print the release's `body` to
   stderr in a bordered box so the user can see what they are
   about to install (or, for `--check`, what the new version
   contains). The box has a `=` rule above and below, a header
   of the form `Release notes for v<version>`, and the body
   taken verbatim from the GitHub release. If `body` is empty
   or missing, print `(no release notes provided)` in place of
   the body. The change log is shown both for `--check` (as
   the last output before exit 0) and for the interactive path
   (immediately before the confirmation prompt in step 7). It
   is **not** re-printed after the install.

7. **Prompt** for confirmation unless `--yes`. The prompt is
   written to stderr; stdin is read for a single character. A
   `y` / `Y` response continues; anything else exits 0 without
   changes.

8. **Detect the running daemon**:
   `systemctl --user is-active --quiet stenographer.service`. If
   the service is `active`, the daemon is running. Run
   `systemctl --user stop stenographer.service` and wait for it
   to drain. The stop is best-effort; if the unit does not exist
   or `systemctl` is unavailable, print a warning and continue.
   `update` does not try to stop one-shot commands (`transcribe`,
   `dictate`); they do not take the single-instance lock and are
   out of scope for this command.

9. **Resolve the install location**:
   `install_root = pathlib.Path(sys.argv[0]).resolve().parent`.
   - If `<install_root>/_internal` exists → onedir PyInstaller
     bundle; the install root is `<install_root>` and the
     launcher is `<install_root>/stenographer`.
   - Otherwise → wheel / pipx install; the install root is
     `<install_root>` and we replace the entire `stenographer`
     Python package under `<install_root>/..` (typically
     `site-packages/stenographer`).
   - Wheel installs print a hint to use `pipx upgrade` /
     `pip install --upgrade` and exit 1 without writing
     anything. v1 only self-updates the onedir bundle.

10. **Download** the tarball to
    `$XDG_DATA_HOME/stenographer/staging/stenographer-<version>.tar.gz`
    (default `~/.local/share/stenographer/staging/...`). Stream
    the response; do not load the full file into memory. On
    network error, exit 1 with a precise message; the old
    install is untouched.

11. **Download and verify** the matching `.sha256` file. Compute
    the SHA-256 of the downloaded tarball with
    `hashlib.sha256()` and compare byte-for-byte. Mismatch →
    exit 1, the old install is untouched.

12. **Extract** the tarball to a staging directory at
    `<install_root>.new.<pid>` (sibling of the install root, on
    the same filesystem so `os.replace` is atomic).

13. **Sanity-check** the new bundle:
    `<staging>/_internal/stenographer/__init__.py` and
    `<staging>/stenographer` (the launcher) must both exist. If
    not, exit 1, the old install is untouched.

14. **Atomic swap**: `os.replace(staging, install_root)`. On
    Linux, this is atomic on the same filesystem. If the swap
    fails (e.g. permissions), the staging dir is left in place
    and the user can investigate; the old install is untouched.

15. **Restart** (unless `--no-restart`):
    `systemctl --user start stenographer.service`. If the unit
    is missing, print a hint and exit 0 anyway (the install
    succeeded; the user can start the daemon by hand).

16. **Report**: print `Updated to v<version>.` and exit 0.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Up to date, or update installed successfully. |
| `1` | Network / download / sha256 / install / restart failure. |
| `2` | CLI usage error (bad flag, etc.). |
| `78` | Configuration / capability failure. |

## Out of scope (v1)

- Updating `pipx` / `pip install --user` installs. The `update`
  command detects a non-onedir install and prints a hint.
- A `--rollback` to the previous bundle. The atomic swap is safe
  in the "new install fails to start" sense, but we do not keep
  N previous bundles on disk.
- Auto-update on a schedule. The user runs `update` interactively.
- Authentication to the GitHub API. The unauthenticated rate
  limit is sufficient.
- Detecting a daemon running outside systemd. `update` only
  knows about the systemd user service.
- Verifying the new binary before swapping (e.g. running
  `doctor`). The sanity check in step 12 is structural (file
  presence) only.
- One-shot commands in flight. `transcribe` and `dictate` are
  not stopped; they complete normally.

## Open questions

- **Concurrent updates.** If the user runs `update` while
  another `update` is downloading, the staging dir will collide.
  v1 detects this with a flock on
  `$XDG_RUNTIME_DIR/stenographer-update.lock` (separate from the
  daemon lock) and exits 1 with "another update is in progress".
  This is a small addition, included in v1.
- **Should the download be retried on transient network errors?**
  v1: no. The user re-runs the command.
