# Windows Parity — Packaging, CI, and the Test Gate

This domain owns the machinery every other domain ships through: the PyInstaller bundle, the
per-user installer, the `windows-latest` build and release jobs, the Windows-only test tree, the
integration smoke harness, and the §D8 merge gate. Blast area is **repo-wide and core-touching** —
it edits `packaging/`, `scripts/`, `.github/workflows/`, `tests/platform/test_core_isolation.py`,
and `AGENTS.md`, all of which Linux executes, so §P7 applies to every item here. It owns no
`platform/windows/` provider module.

## Designed source tree

Rows from README §T that belong to this domain:

```
packaging/
├── stenographer.spec                       EDIT  per-OS inputs, sourced from spec_support
scripts/
└── install.ps1                             NEW   per-user installer, %LOCALAPPDATA%\Programs
tests/platform/windows/                     NEW   Windows-only tests, not collected elsewhere
.github/workflows/
├── build.yml                               EDIT  windows-latest bundle job
└── release.yml                             EDIT  Windows zip + checksums
```

Files this domain also touches that README §T does not enumerate (§T covers `src/`, `scripts/`,
`packaging/`, `tests/` and `.github/workflows/` only; it lists no documentation, test-support, or
per-file test rows). Each is an addition to §T that the README owner should fold in:

```
packaging/
├── spec_support.py                         NEW   pure per-OS spec inputs (§P5 target for the spec)
├── entry.py                                —     verified unchanged; carries over verbatim
├── hook-sounddevice.py                     —     verified unchanged; deregistered on Windows
└── rthooks/py_rth_portaudio.py             —     verified unchanged; deregistered on Windows
scripts/
└── merge_gate.py                           NEW   pure §D8 path→suite resolver + attestation parser
tests/
├── platform/windows/conftest.py            NEW   collection guard + shared smoke fixtures
├── platform/windows/harness.py             NEW   not collected; skip_reason + self-owned window
├── platform/windows/test_harness.py        NEW   pure tests for the skip policy
├── platform/windows/test_harness_smoke.py  NEW   harness self-verification
├── platform/test_collection_guards.py      NEW   both guards, asserted from both OSes
├── platform/test_core_isolation.py         EDIT  Windows provider submodules import on any host
├── test_packaging_spec.py                  NEW   pure tests for spec_support
└── test_merge_gate.py                      NEW   pure tests for the §D8 resolver
.github/
├── workflows/test.yml                      EDIT  collection assertions + `merge gate` job
└── pull_request_template.md                NEW   the two smoke attestation checkboxes
AGENTS.md                                   EDIT  rule 10 gains the §D8 scoping sentence
BUILD.md                                    EDIT  Windows build, install, smoke runner, signing
pyproject.toml                              —     verified unchanged; see WIN-PKG-03
```

## Architecture principles

Global rules are in README §P and are not restated. These are the ones a packaging or CI change can
break while everything still builds.

- **WIN-PKG-P1 — One `Analysis`, one spec, no branches in the spec body.** All OS variation is data
  returned by pure functions in `packaging/spec_support.py`, keyed on a `platform: str` argument.
  `packaging/stenographer.spec` binds `sys.platform` exactly once and passes it down. Reviewer
  check: `grep -c 'sys\.platform' packaging/stenographer.spec` is `1`, and the file contains no
  `if`/`else` around `Analysis`, `EXE`, or `COLLECT` arguments.
- **WIN-PKG-P2 — The Windows bundle carries PortAudio; the Linux bundle never does.** BUILD.md's
  rule ("libportaudio is a required *system* dependency and MUST NOT be bundled") is a Linux rule.
  Windows has no system PortAudio: the `sounddevice` wheel's
  `_sounddevice_data/portaudio-binaries/libportaudio*.dll` is the only copy and must ship. The
  mechanism is deregistration, not a second hook — `hook_paths("win32")` is empty so PyInstaller's
  bundled `sounddevice` hook collects the DLL, and `packaging/hook-sounddevice.py` stays a Linux
  artifact, unedited.
- **WIN-PKG-P3 — Two executables from one `Analysis`.** Console `stenographer.exe` serves every CLI
  subcommand and the developer `run` loop; windowed `stenographerw.exe` is the logon-task target and
  exists only so a `schtasks /sc ONLOGON` action does not paint a console window on every sign-in
  (the `python.exe`/`pythonw.exe` precedent). Never a second `Analysis()` — it doubles build time and
  the two can drift. Accepted consequence, which WIN-LIFE must handle: `stenographerw.exe` owns no
  console, so `SetConsoleCtrlHandler` registration must be a probed no-op there.
- **WIN-PKG-P4 — The installer never needs administrator.** `scripts/install.ps1` writes only under
  `%LOCALAPPDATA%` and `HKCU`. Any command requiring elevation is *printed* for the user to run, never
  executed. Reviewer check: `Start-Process -Verb RunAs`, `Add-MpPreference`, `HKLM:`, and
  `$env:ProgramFiles` may appear only inside a quoted string that is written to stdout.
- **WIN-PKG-P5 — The scheduled-task argv has one source of truth.** `install.ps1` never spells a
  `schtasks` flag. It obtains the argv from WIN-LIFE's pure builder through the repo venv, prints it,
  then executes it. A second copy of the argv in PowerShell is the defect this forbids.
- **WIN-PKG-P6 — Smoke modules gate through `harness.skip_reason` and nothing else.** The single
  policy requires `sys.platform == "win32"`, `STENOGRAPHER_INTEGRATION=1`, and the *absence* of `CI`,
  plus each module's declared prerequisites. No smoke module hand-rolls an env check; a suite that
  silently skips everything turns the merge gate into a lie, so the guard is itself unit-tested.
- **WIN-PKG-P7 — Windows-only test code lives under `tests/platform/windows/` and nowhere else.** No
  test outside that tree may branch on `sys.platform == "win32"` to add Windows behavior. The two
  deliberate exceptions run on every host by design: `tests/platform/test_core_isolation.py` and
  `tests/platform/test_collection_guards.py`.
- **WIN-PKG-P8 — Release artifacts are verified by content on a different runner than built them.**
  Every artifact gets `sound_asset_guard.py`, a `--version` equality assertion against the preflight
  output, and a checksum written on the build runner and re-checked in the `release` job. Existence
  checks (`Test-Path`) never substitute for content checks.
- **WIN-PKG-P9 — The merge gate fails closed.** `required_suites()` returns both suites for any path
  it does not recognize. A new top-level directory must never silently require no smoke run.

## Functional criteria

### WIN-PKG-01 — Build the Windows smoke harness and its collection guard
Phase: 1   Depends on: none
Files: `tests/platform/windows/conftest.py` (NEW), `tests/platform/windows/harness.py` (NEW),
`tests/platform/windows/test_harness.py` (NEW), `tests/platform/windows/test_harness_smoke.py` (NEW)
Pure tests: `tests/platform/windows/test_harness.py::test_skip_reason_requires_the_integration_env_var`,
`::test_skip_reason_refuses_to_run_under_ci`,
`::test_skip_reason_reports_a_missing_prerequisite_separately`,
`::test_skip_reason_returns_none_when_every_prerequisite_holds`
Smoke: `windows_harness_selftest`
Done when: a Windows-only test file added to `tests/platform/windows/` is collected by
`.venv\Scripts\pytest` on Windows, contributes zero collected items on Linux, and can obtain a
focused, self-owned text window and a unique clipboard marker without editing `conftest.py` or
`harness.py`.

`conftest.py` mirrors `tests/platform/linux/conftest.py` exactly:
`collect_ignore_glob = [] if sys.platform == "win32" else ["*.py"]`. `harness.py` carries no `test_`
prefix so it is never collected, and exports:

- `skip_reason(env: Mapping[str, str], platform: str, prerequisites: Mapping[str, bool]) -> str | None`
  — pure; the single gate of WIN-PKG-P6. Returns a reason string for: not `win32`;
  `STENOGRAPHER_INTEGRATION != "1"`; `CI` present in `env`; any prerequisite `False`. `None` only when
  all hold.
- `foreground_edit_window()` — context manager. `RegisterClassW` a per-process-unique class, create an
  overlapped window with a child `EDIT` control, pump messages on a dedicated thread,
  `SetForegroundWindow`, expose `.hwnd`, `.text()` (via `WM_GETTEXT`), `.clear()`. This is the
  self-owned window every injection case in other domains targets.
- `pump_until(predicate, timeout_s)` — bounded wait that keeps the window's message loop alive.
- `unique_marker()` — a uuid4 string for clipboard round-trips.

`conftest.py` re-exports these as fixtures `foreground_edit_window`, `clipboard_marker`, and
`smoke_gate` so a new smoke module needs no import of `harness` beyond the fixture names.

### WIN-PKG-02 — Prove the Windows provider imports on a Linux host
Phase: 1   Depends on: none
Files: `tests/platform/test_core_isolation.py` (EDIT)
Pure tests: `tests/platform/test_core_isolation.py::test_windows_provider_submodules_import_on_any_host`
Smoke: none — an import test needs no machine; it is the cheapest possible check of README §P1 and
runs in the existing `test` and `unit-windows` jobs.
Done when: every module under `stenographer.platform.windows` imports in a fresh interpreter on Linux,
so `collect_submodules("stenographer")` in the Linux bundle cannot be broken by a Windows provider
module that touches Win32 at import time.

The test walks `stenographer.platform.windows.__path__` with `pkgutil.walk_packages` in a subprocess
and imports every name. It is the enforcement of README §P1's last sentence; without it the failure
surfaces only in the `build release binary` job on a PR to `main`. Linux behavior that must stay
byte-identical (§P7): the existing
`test_core_imports_with_linux_only_modules_blocked` is unchanged — the new function is additive and
shares no state.

### WIN-PKG-03 — Extract `packaging/spec_support.py` and make the spec per-OS
Phase: 4   Depends on: none
Files: `packaging/spec_support.py` (NEW), `packaging/stenographer.spec` (EDIT),
`tests/test_packaging_spec.py` (NEW)
Pure tests: `tests/test_packaging_spec.py::test_windows_drops_the_local_hook_path`,
`::test_pywayland_inputs_are_linux_only`, `::test_linux_only_hidden_imports_are_absent_on_windows`,
`::test_windows_builds_a_windowed_executable_beside_the_console_one`,
`::test_runtime_hooks_are_linux_only`, `::test_archive_name_is_per_os`,
`::test_linux_spec_inputs_match_the_pre_refactor_values`
Smoke: `windows_bundle_launch`
Done when: `.venv/bin/pyinstaller --noconfirm --clean packaging/stenographer.spec` produces the same
Linux bundle as before the refactor, and the same command on Windows produces
`dist\stenographer\stenographer.exe`, `dist\stenographer\stenographerw.exe`, and a bundled
`libportaudio*.dll`, with no `pywayland` or `evdev` anywhere in `_internal`.

`spec_support.py` is stdlib-only, imports no PyInstaller symbol, and exposes pure functions taking a
`platform: str`:

| Function | `"linux"` | `"win32"` |
|---|---|---|
| `hook_paths(platform, packaging_dir)` | `[str(packaging_dir)]` | `[]` (WIN-PKG-P2) |
| `runtime_hooks(platform, rthook_dir)` | `[py_rth_portaudio.py]` | `[]` |
| `hidden_imports(platform)` | base + `evdev`, `evdev._ecodes`, `pywayland._ffi` | base only |
| `pywayland_binaries(platform, find_spec, get_imports)` | current logic, still `RuntimeError` when missing | `[]`, no lookup |
| `executables(platform)` | one `ExeSpec("stenographer", console=True)` | that plus `ExeSpec("stenographerw", console=False)` |
| `archive_name(platform, version, arch)` | `stenographer-{v}-linux-{arch}.tar.gz` | `stenographer-{v}-windows-{arch}.zip` |

Carry-over verdict for the rest of `packaging/`, which SCOPE.md §5 called "mostly carries over":

- `packaging/entry.py` — **carries over verbatim.** `multiprocessing.freeze_support()` is already
  called there and again in `cli/__init__.py`; the ASR worker already uses
  `get_context("spawn")`, which is what Windows requires. No edit.
- `packaging/hook-sounddevice.py` — **does not carry over, and is not edited.** Its
  `excludedbinaries = ["libportaudio*", ...]` is correct on Linux and fatal on Windows; the file is
  deregistered by `hook_paths("win32") == []` rather than made conditional, so PyInstaller's own
  `sounddevice` hook collects the DLL.
- `packaging/rthooks/py_rth_portaudio.py` — **does not carry over, and is not edited.** It mutates
  `LD_LIBRARY_PATH` from a hardcoded list of Linux directories; `runtime_hooks("win32")` is empty.
- `pyproject.toml` — **verified: no change required.** `evdev`, `pywayland` and `python-xlib` already
  carry `sys_platform == 'linux'`; SCOPE.md §6's near-zero-new-dependency verdict holds because the
  provider is `ctypes` + `msvcrt` reusing `sounddevice`/`soundfile` and PowerShell. This item's
  `Done when` includes "no dependency and no `sys_platform == 'win32'` marker was added"; adding one
  is a §6 amendment, not a packaging change.

Linux behavior that must stay byte-identical (§P7): `test_linux_spec_inputs_match_the_pre_refactor_values`
asserts each `spec_support` function's `"linux"` return against the literal values the spec carried
before the refactor, and `build.yml`'s existing `build release binary` and `build release binary
(ARM64)` jobs remain the end-to-end proof.

### WIN-PKG-04 — Write `scripts/install.ps1`, the admin-free per-user installer
Phase: 4   Depends on: WIN-PKG-03, `WIN-LIFE: schtasks logon-task argv builder (elevated flag)`
Files: `scripts/install.ps1` (NEW)
Pure tests: none — PowerShell has no unit runner in this repo, and the only extractable logic (the
task argv) is WIN-LIFE's pure builder by WIN-PKG-P5. Syntax is checked in CI by
`[System.Management.Automation.Language.Parser]::ParseFile`, the analog of `bash -n` in
`scripts/check-completions.sh`; behavior is covered by `windows_installer_roundtrip`.
Smoke: `windows_installer_roundtrip`
Done when: on a clean user profile with no administrator rights, `pwsh -File scripts\install.ps1`
leaves a runnable `stenographer` on `PATH`, a registered `stenographer` logon task, and no UAC prompt;
`pwsh -File scripts\install.ps1 -Uninstall` removes all three.

Parameters: `-InstallDir` (default `$env:LOCALAPPDATA\Programs\stenographer`), `-NoRegister`,
`-NoStart`, `-Elevated`, `-Uninstall`. Header is `#Requires -Version 5.1`,
`Set-StrictMode -Version Latest`, `$ErrorActionPreference = 'Stop'`. Steps, mirroring
`scripts/install.sh` and README §D2 (which records that `install.sh` genuinely installs, enables and
starts the unit, correcting SCOPE.md §4 — so registering the task is the correct parity, and the
print-only policy stays with `doctor`/`setup`):

1. Build if `dist\stenographer\stenographer.exe` is absent:
   `.venv\Scripts\pyinstaller --noconfirm --clean packaging\stenographer.spec`.
2. `schtasks /end /tn stenographer` (failure ignored). Stronger than `install.sh`'s stop step:
   Windows refuses to overwrite a mapped image, so the copy *fails* rather than silently leaving a
   stale process.
3. Clear and copy `dist\stenographer\*` into `-InstallDir`.
4. `Unblock-File` every `*.exe`, `*.dll`, `*.pyd` under the install dir — clears Mark-of-the-Web on
   the copied tree (WIN-PKG-10).
5. Append `-InstallDir` to the **user** `Path` via
   `[Environment]::SetEnvironmentVariable('Path', ..., 'User')`, idempotently. No symlink: symlink
   creation needs admin or Developer Mode, so the Linux `~/.local/bin` symlink has no parity here.
6. Verify the frozen completions still emit: `stenographer.exe completion bash|zsh|fish` must each be
   non-empty (the check `scripts/build.sh` performs). Nothing is *installed* — Windows has no standard
   per-user completion directory and decision 4 fixes the surface at Bash/Zsh/Fish — so the script
   prints the redirect command instead.
7. Unless `-NoRegister`: obtain the argv from
   `.venv\Scripts\python -c "from stenographer.platform.windows.service import ..."` per WIN-PKG-P5,
   print it, and execute it. `-Elevated` selects WIN-LIFE's `/rl HIGHEST` variant; the default is
   medium integrity per README §D7, and the script prints the UIPI trade in one line.
8. Unless `-NoStart`: `schtasks /run /tn stenographer`.
9. Summary: install dir, task name, `schtasks /query /tn stenographer`, `stenographer doctor`,
   `stenographer model download` (~1.5 GB, never bundled), the new-shell-needed `PATH` note, and the
   unsigned-bundle SmartScreen note from WIN-PKG-10.

### WIN-PKG-05 — Add the `windows-latest` bundle job to `build.yml`
Phase: 4   Depends on: WIN-PKG-03, WIN-PKG-04
Files: `.github/workflows/build.yml` (EDIT)
Pure tests: none — a workflow is verified by running; its assertions are the deliverable.
Smoke: none — CI never runs the smoke suite (WIN-PKG-P6).
Done when: a PR to `main` runs a job named `build release binary (Windows)` that builds the bundle on
`windows-latest` and fails if PortAudio is missing from it, if `stenographerw.exe` is missing, if
`evdev`/`pywayland` appear in `_internal`, or if `scripts/install.ps1` does not parse.

Job id `build-release-windows`, `runs-on: windows-latest`, `timeout-minutes: 60`, steps:
`actions/checkout@v7` (`persist-credentials: false`), `actions/setup-python@v7` at `3.12`,
`python -m venv .venv`, `.venv\Scripts\pip install -e ".[build]"`,
`.venv\Scripts\pyinstaller --noconfirm --clean packaging\stenographer.spec`, then assertions:

- `.venv\Scripts\python scripts\sound_asset_guard.py dist\stenographer\_internal\stenographer\assets\sounds`
- `dist\stenographer\stenographer.exe --version` and `--help`
- `Test-Path dist\stenographer\stenographerw.exe`
- `(Get-ChildItem dist\stenographer\_internal -Recurse -Filter 'libportaudio*.dll').Count -ge 1`
- `-not (Test-Path dist\stenographer\_internal\evdev)` and `...\pywayland`
- each of `completion bash|zsh|fish` emits non-empty output
- `install.ps1` parses with zero `[ref]` errors

No Windows ARM64 job: GitHub's Windows Arm runners are out of scope for this phase; the archive name
carries the arch (WIN-PKG-03) so adding one later is a matrix row, not a rename.

**Repository-admin action, not a code change:** the `main` ruleset requires exact check names
(hence the comment on `build-release`). Adding `build release binary (Windows)` to the required set is
a settings change a maintainer must make; until then the job runs but does not block.

### WIN-PKG-06 — Publish a Windows zip and checksums from `release.yml`
Phase: 4   Depends on: WIN-PKG-03, WIN-PKG-05
Files: `.github/workflows/release.yml` (EDIT)
Pure tests: `tests/test_packaging_spec.py::test_archive_name_is_per_os` (shared with WIN-PKG-03 —
the workflow and the spec must agree on one name)
Smoke: `windows_bundle_launch` (run against the *downloaded release zip*, not a local build)
Done when: a push to `main` that changes `src/**`, `pyproject.toml`, `packaging/**` or
`scripts/build.sh` refreshes a draft release carrying
`stenographer-<version>-windows-x86_64.zip` alongside both Linux tarballs and the Python
distributions, with every entry present in the single `SHA256SUMS` asset.

New job `standalone-windows`, name `build standalone (windows-x86_64)`,
`needs: [preflight, lint, test]`, `runs-on: windows-latest`. It mirrors the `standalone` job:

- build, then `test "$(stenographer.exe --version)" = "${{ needs.preflight.outputs.version }}"`
- `Copy-Item LICENSE dist\stenographer\LICENSE`
- zip with Python, not `Compress-Archive`:
  `.venv\Scripts\python -c "import shutil; shutil.make_archive(...)"`. PowerShell 5.1's
  `Compress-Archive` writes backslash-separated entry names, which `scripts/sound_asset_guard.py`'s
  `_zip_entries` prefix match would not recognize.
- `.venv\Scripts\python scripts\sound_asset_guard.py release\<zip> --prefix stenographer/_internal/stenographer/assets/sounds`
- checksum in `sha256sum(1)` format so the ubuntu `release` job's `sha256sum --check` accepts it:
  `"{0}  {1}" -f $h.Hash.ToLower(), $name` — lowercase hex, **two** spaces, LF newline.
- `actions/upload-artifact@v7` as `release-standalone-windows-x86_64`.

The `release` job gains the zip in its `artifacts` array, `sha256sum --check
release-windows-x86_64.SHA256SUMS` plus the matching `rm`, and the zip in its `assets` array so
`actions/attest` and the asset re-upload cover it. `on.push.paths` needs no new entry:
`packaging/**` already covers `spec_support.py`. Do **not** add `scripts/install.ps1` to that filter —
it is an artifact-input list, and the installer is not an artifact.

### WIN-PKG-07 — Assert the collection guards in both directions
Phase: 1   Depends on: WIN-PKG-01
Files: `tests/platform/test_collection_guards.py` (NEW), `.github/workflows/test.yml` (EDIT)
Pure tests: `tests/platform/test_collection_guards.py::test_foreign_platform_tree_collects_nothing`,
`::test_native_platform_tree_collects_something`
Smoke: none — collection is observable from a subprocess on any host.
Done when: the `test` job fails if `tests/platform/windows/` ever collects on Linux, and the
`unit-windows` job fails if `tests/platform/windows/` collects **zero** tests on Windows.

The failure this exists to catch is silent, not loud: a typo in `conftest.py`'s guard makes the whole
Windows suite vanish from `unit-windows` while the job stays green. The test shells out to
`pytest --collect-only -q <foreign tree>` and asserts exit code 5 (no tests collected), and to the
native tree asserting a nonzero count. `test.yml` gains one step per job asserting the same thing at
the workflow level, so the signal survives even if the test file is deleted. `unit-windows` needs no
other change: it already runs `.venv\Scripts\pytest -m "not integration"` over `tests`, so every pure
test another domain adds under `tests/platform/windows/` is picked up with no workflow edit.

### WIN-PKG-08 — Make the §D8 merge gate enforceable
Phase: 4   Depends on: none
Files: `scripts/merge_gate.py` (NEW), `tests/test_merge_gate.py` (NEW),
`.github/workflows/test.yml` (EDIT), `.github/pull_request_template.md` (NEW), `AGENTS.md` (EDIT)
Pure tests: `tests/test_merge_gate.py::test_linux_provider_paths_require_only_the_linux_suite`,
`::test_windows_provider_paths_require_only_the_windows_suite`,
`::test_core_paths_require_both_suites`, `::test_mixed_provider_paths_require_both_suites`,
`::test_sibling_path_prefixes_do_not_match_a_provider_tree`,
`::test_unrecognized_path_fails_closed_to_both`, `::test_empty_diff_requires_no_suite`,
`::test_attestation_must_cover_every_required_suite`
Smoke: none — the rule is text and path arithmetic; no machine is involved.
Done when: a PR to `main` runs a job named `merge gate` that prints which real-machine suites README
§D8 requires for that PR's changed paths and fails unless the PR body attests to each of them.

`scripts/merge_gate.py` follows `scripts/release_guard.py`'s shape: a pure core, a thin CLI, a
`MergeGateError`, and `--github-output`. Its core is

```
required_suites(paths: Iterable[str]) -> frozenset[str]      # "linux", "windows"
missing_attestations(required: frozenset[str], body: str) -> tuple[str, ...]
```

implementing README §D8's table verbatim; the policy is not re-argued here. Per WIN-PKG-P9 the third
row is read as written — *anything else* requires both — so an unrecognized path resolves to both
suites rather than to none. The attestation tokens are `[x] linux smoke green` and
`[x] windows smoke green`, seeded by `.github/pull_request_template.md`. `AGENTS.md` rule 10 gains one
sentence pointing at README §D8 and at `.venv/bin/python scripts/merge_gate.py --diff-base origin/main`,
which a contributor runs locally to learn which suite applies before opening the PR.

The honest limit, stated in the job's output and in `AGENTS.md`: automation checks that the
attestation is *present and matches the computed requirement*. It cannot verify the run happened.
That is the same trust model rule 10 has always had; the automation removes the "which suite did I
need?" question, not the human.

### WIN-PKG-09 — Document the Windows build, install, and smoke runner in `BUILD.md`
Phase: 4   Depends on: WIN-PKG-01, WIN-PKG-03, WIN-PKG-04, WIN-PKG-06
Files: `BUILD.md` (EDIT)
Pure tests: none — documentation.
Smoke: none.
Done when: a contributor with a clean Windows machine, the repo, and Python 3.12 can build, install,
and run the full Windows smoke suite from `BUILD.md` alone, without reading any file under
`docs/windows/`.

The section covers: the venv (`python -m venv .venv`, `.venv\Scripts\pip install -e ".[dev,build]"`),
the direct PyInstaller invocation (there is no `build.ps1`; `scripts/build.sh`'s value is its progress
bar, and the spec header already documents the direct command), `scripts\install.ps1` and its
switches, the two executables and which one the logon task uses (WIN-PKG-P3), and the smoke runner:

```
$env:STENOGRAPHER_INTEGRATION = "1"
.venv\Scripts\pytest -m integration -ra
```

with its prerequisites spelled out — a real interactive desktop session (never a sandbox, never CI;
`CI` in the environment aborts the suite by WIN-PKG-P6), a working microphone, and
`.venv\Scripts\stenographer model download` having been run, since the ~1.5 GB model is never bundled
and every model-loading case self-skips without it. The section states that `-ra` output must be read,
not just the exit code: a suite that skipped everything also exits 0.

### WIN-PKG-10 — Cost and defer Authenticode signing; land the free mitigations
Phase: 4   Depends on: WIN-PKG-04, WIN-PKG-06
Files: `BUILD.md` (EDIT), `scripts/install.ps1` (EDIT), `.github/workflows/release.yml` (EDIT)
Pure tests: none — a procurement decision plus two one-line mitigations.
Smoke: `windows_installer_roundtrip` covers the `Unblock-File` step.
Done when: `BUILD.md` states exactly what signing costs and unblocks, `release.yml` carries a named
commented-out `Sign Windows artifacts` step at the point it would run, the draft release body notes
the artifacts are unsigned, and `install.ps1` clears Mark-of-the-Web from the installed tree.

Per README §D7, signing is a cost decision, not a code one. What it requires:

- An OV or EV Authenticode certificate. Since the 2023 CA/B Forum change the private key must live on
  FIPS 140-2 Level 2 hardware or in a cloud signing service — a token cannot be avoided by paying more.
  Practical options: a hardware-token OV certificate (roughly $200–400/yr plus token), an EV
  certificate (roughly $300–700/yr), or Azure Trusted Signing (~$10/month, subject to its identity
  requirements). All require verifying a legal identity, which is a maintainer decision, not a PR.
- A signing step: `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256` from the Windows SDK, or
  `azuresigntool`, applied to `stenographer.exe`, `stenographerw.exe`, and the `.dll`/`.pyd` files under
  `_internal\` — Defender scores the tree, SmartScreen scores only the launched image.
- A CI secret or federated identity, which makes the release workflow capable of signing anything in
  the repo. That is the change with the largest blast radius here and the reason it is not landed
  speculatively.

What it unblocks, precisely:

- **SCOPE.md §7 risk 2** — an EV certificate grants SmartScreen reputation immediately; an OV
  certificate must still accrue reputation, so signing alone does not remove the warning. Defender's
  heuristic match against a global-keyboard-hook binary improves with any valid signature.
- **SCOPE.md §7 risk 1, only in combination.** `uiAccess="true"` in the manifest is the mechanism that
  lets a medium-integrity process drive a higher-integrity foreground window, and it requires *both*
  an Authenticode signature *and* installation under a secure location (`%ProgramFiles%` or
  `%WinDir%`). That contradicts README §D7's no-admin `%LOCALAPPDATA%\Programs` model, so risk 1
  needs signing **plus** an admin install path — a separate decision, not a consequence of signing.

Landed now, at zero cost: `install.ps1`'s `Unblock-File` sweep (step 4 of WIN-PKG-04) removes the
Zone.Identifier stream from every extracted binary, which is what produces "Windows protected your PC"
on first launch of a downloaded bundle; the printed-only `Add-MpPreference -ExclusionPath` suggestion
for users who hit a Defender quarantine (printed, never run — WIN-PKG-P4); and the existing
`SHA256SUMS` plus `actions/attest` provenance, which is the substitute for a signature until one is
bought.

## Acceptance criteria

**WIN-PKG-01.** `test_skip_reason_requires_the_integration_env_var` must fail against a guard that
returns `None` when `STENOGRAPHER_INTEGRATION` is unset — the bug that makes the whole smoke suite run
during an ordinary `pytest`. `test_skip_reason_refuses_to_run_under_ci` must fail against a guard that
omits the `CI` check, given `{"CI": "true", "STENOGRAPHER_INTEGRATION": "1"}`; that guard would let a
runner create foreground windows and register scheduled tasks, which AGENTS.md forbids outright.
`test_skip_reason_reports_a_missing_prerequisite_separately` must fail against a guard that collapses
"model not downloaded" into the same reason string as "integration not enabled" — the two are
distinguishable in `-ra` output and a maintainer must be able to tell "you forgot the env var" from
"you forgot the 1.5 GB download". `test_skip_reason_returns_none_when_every_prerequisite_holds` must
fail against a guard that skips unconditionally, which would make the merge gate vacuous.

Smoke `windows_harness_selftest`, in `tests/platform/windows/test_harness_smoke.py`: with
`STENOGRAPHER_INTEGRATION=1` on a real desktop session, open `foreground_edit_window()`, confirm
`GetForegroundWindow()` returns its `hwnd`, synthesize literal characters into it, and assert
`.text()` returns them within `pump_until(..., 2.0)`. This verifies the window is real and focusable;
it deliberately does not exercise a paste chord, which belongs to WIN-DELIV.

*The harness's own acceptance criterion is extensibility.* Demonstration, checkable by a reviewer:
take any smoke case named in another domain's Acceptance criteria section, add one file
`tests/platform/windows/test_<area>_smoke.py` whose entire preamble is `pytestmark =
pytest.mark.integration` plus a `skip_reason` gate, request the `foreground_edit_window` and
`clipboard_marker` fixtures by name, and confirm that (a) it runs under
`STENOGRAPHER_INTEGRATION=1`, (b) it is skipped with a readable reason without it, (c) it collects
zero items on Linux, and (d) `git diff --stat` for that change shows **no** modification to
`tests/platform/windows/conftest.py` or `tests/platform/windows/harness.py`. A change to either file
in a case-adding PR is the failure of this criterion.

**WIN-PKG-02.** `test_windows_provider_submodules_import_on_any_host` must be seen to fail on Linux
after temporarily adding `from ctypes import windll` (or `from ctypes import wintypes`) at module
scope in any `platform/windows/*.py` — the exact edit that also breaks
`collect_submodules("stenographer")` and therefore the *Linux* release bundle (README §P1). Observable
behavior: the `test` job on `ubuntu-latest` and the `unit-windows` job both go red on that edit,
instead of only `build release binary` on a PR to `main`.

**WIN-PKG-03.** `test_windows_drops_the_local_hook_path` must fail against `hook_paths` returning the
packaging directory on `win32`; that configuration excludes `libportaudio*` from the Windows bundle
and the resulting `stenographer.exe run` dies at the first `import sounddevice` with "PortAudio
library not found". `test_pywayland_inputs_are_linux_only` must fail against the current
unconditional `find_spec("pywayland._ffi")` / `raise RuntimeError` block, which aborts every Windows
build before `Analysis` — assert `pywayland_binaries("win32", ...) == []` with the lookups never
called, and that `"linux"` with a `None` finder still raises. `test_linux_only_hidden_imports_are_absent_on_windows`
must fail against a shared literal list containing `evdev`. `test_windows_builds_a_windowed_executable_beside_the_console_one`
must fail against a single-executable build: the observable defect is a console window painted on the
user's desktop at every logon. `test_runtime_hooks_are_linux_only` must fail against registering
`py_rth_portaudio.py` on Windows. `test_archive_name_is_per_os` must fail against a name that omits
the platform, which would make the Linux and Windows release assets collide.
`test_linux_spec_inputs_match_the_pre_refactor_values` is the §P7 proof and must fail against any
change to the Linux inputs; the end-to-end proof remains the unchanged `build release binary` and
`build release binary (ARM64)` jobs.

Smoke `windows_bundle_launch`: on a Windows machine with **no repo, no venv, and no Python
installed**, extract the bundle, run `stenographer.exe --version` (matches the release version),
`--help`, `doctor` (exits 0 once the provider is complete, 78 before that), and
`completion bash|zsh|fish` (each non-empty). Observable behavior: no `ModuleNotFoundError`, no missing
DLL dialog, no console window from `stenographerw.exe --version`.

**WIN-PKG-04.** Smoke `windows_installer_roundtrip`, run from a *non-elevated* PowerShell on a clean
profile:

1. `pwsh -File scripts\install.ps1` completes with **no UAC prompt** — the observable check for
   WIN-PKG-P4. Watch for the consent dialog; its appearance fails the case outright.
2. `%LOCALAPPDATA%\Programs\stenographer\stenographer.exe` exists; a **new** shell resolves
   `stenographer` from `PATH`.
3. `schtasks /query /tn stenographer /v /fo list` shows an `ONLOGON` trigger and, by default, a
   run level that is not `HIGHEST` (README §D7).
4. Re-run the installer over the running daemon: it stops the task first, and the copy succeeds — the
   step that fails loudly if omitted, because Windows refuses to overwrite a mapped image.
5. `pwsh -File scripts\install.ps1 -Uninstall` removes the task, the directory, and the `PATH` entry;
   `schtasks /query /tn stenographer` then reports the task does not exist.
6. `-Elevated` registers with `/rl HIGHEST` and prints the UIPI trade; `-NoRegister` prints the argv
   and registers nothing.

The argv printed in step 6 must be character-identical to what WIN-LIFE's builder returns — the
observable check for WIN-PKG-P5. A reviewer greps `scripts/install.ps1` for `/sc`, `/tn`, `/tr`,
`/rl`: none may appear outside the printed result of the builder call.

**WIN-PKG-05.** Observable behavior on a PR to `main`: the `build release binary (Windows)` check
appears and is green. Each assertion is verified by breaking it once — set `hook_paths("win32")` back
to the packaging directory and confirm the `libportaudio*.dll` assertion fails; drop the second
`ExeSpec` and confirm the `stenographerw.exe` assertion fails; introduce a stray `)` in
`install.ps1` and confirm the parse step fails. No mock is involved at any point: the job builds a
real bundle and inspects real files.

**WIN-PKG-06.** Observable behavior: a push to `main` produces a draft release whose asset list
contains `stenographer-<version>-windows-x86_64.zip`, and whose single `SHA256SUMS` verifies with
`sha256sum --check` on the ubuntu `release` runner — the cross-runner check of WIN-PKG-P8. Verified by
breaking it once: emit the checksum with uppercase hex or a single space and confirm the `release` job
fails at `sha256sum --check`. The `windows_bundle_launch` smoke case is re-run against the
**downloaded** zip, not a local `dist/`, to prove the archive round-trip preserved the tree;
`sound_asset_guard.py` on the zip is the automated half of the same claim.

**WIN-PKG-07.** `test_foreign_platform_tree_collects_nothing` must fail after deleting
`tests/platform/windows/conftest.py`: on Linux the collection subprocess then exits 1 or 2 with
import errors from Win32-only modules rather than 5. `test_native_platform_tree_collects_something`
must fail against a guard written as `collect_ignore_glob = ["*.py"]` unconditionally, or against
`sys.platform.startswith("win")` typo'd to a value that never matches — the silent-disable bug. The
`unit-windows` step asserting a nonzero collected count is the workflow-level duplicate that survives
deletion of the test file. Observable behavior: adding a pure test under `tests/platform/windows/`
changes the `unit-windows` collected count with no workflow edit.

**WIN-PKG-08.** `test_linux_provider_paths_require_only_the_linux_suite` must fail against a resolver
that returns both suites for `src/stenographer/platform/linux/uinput.py`, which would make every Linux
provider change wait for a Windows machine. `test_core_paths_require_both_suites` must fail against a
row-3 implementation restricted to `src/stenographer/**`: feed it `pyproject.toml`,
`scripts/install.sh`, and `packaging/stenographer.spec`, each of which §D8 names explicitly.
`test_sibling_path_prefixes_do_not_match_a_provider_tree` must fail against a `startswith("tests/platform/linux")`
implementation, given `tests/platform/linux_helpers.py` — a path that is not inside the provider tree
and must therefore resolve to both suites. `test_unrecognized_path_fails_closed_to_both` must fail
against a resolver returning an empty set for a path under a directory that does not exist today
(WIN-PKG-P9). `test_empty_diff_requires_no_suite` must fail against a resolver that returns both for
an empty input, which would block an empty PR forever.
`test_attestation_must_cover_every_required_suite` must fail against a parser satisfied by one
checkbox when two are required, and against one that accepts an unchecked `[ ]` box.

Observable behavior: open a PR touching only `src/stenographer/platform/windows/clipboard.py` and the
`merge gate` job demands the Windows attestation alone; add one line to `status.py` to the same PR and
it demands both. Locally,
`.venv/bin/python scripts/merge_gate.py --diff-base origin/main` prints the same answer.

**WIN-PKG-09.** Verified by handing `BUILD.md` to someone who has not read `docs/windows/` and
watching them reach a green `windows_bundle_launch` on a fresh machine without asking a question. The
mechanical check: every command in the new section is copy-pasteable and every prerequisite that can
block the smoke suite — desktop session, microphone, `model download`, absent `CI` — is named in it.

**WIN-PKG-10.** `BUILD.md` names a specific certificate class, a specific annual cost range, a
specific signing command, and the two risks it does and does not close; a reviewer checking this
criterion is checking for the absence of hedging, not for a decision. `release.yml` carries a
commented `Sign Windows artifacts` step positioned between the archive step and the upload step, so
enabling it later is an uncomment plus a secret. The `Unblock-File` step is exercised by
`windows_installer_roundtrip`: after install, `Get-Item <install-dir>\stenographer.exe -Stream *`
must not list `Zone.Identifier`. Observable behavior: launching the installed
`stenographer.exe` from Explorer on a machine that downloaded the release zip shows no "Windows
protected your PC" dialog attributable to Mark-of-the-Web, though an unsigned-binary Defender or
SmartScreen prompt may still appear — which is precisely the residue that only signing removes.

## Risks

**R1 — Antivirus and SmartScreen on the unsigned bundle (SCOPE.md §7 risk 2).** The largest risk in
this domain. Likelihood: high — an unsigned PyInstaller onedir that installs `WH_KEYBOARD_LL` matches
the keylogger heuristic directly, and Defender quarantines the whole install directory rather than
warning. Impact: severe for distribution — the release artifacts become unusable for anyone who is not
willing to click through or add an exclusion, and a quarantine mid-install leaves a half-copied tree.
Mitigation: the free half is landed by WIN-PKG-10 (Mark-of-the-Web cleared, printed exclusion
guidance, provenance attestation, unsigned status stated in the release notes) and README §D7's
medium-integrity default, which keeps the bundle out of the worst heuristic bucket (unsigned + global
hook + administrator). The real fix is priced and deferred in WIN-PKG-10. Covered by: WIN-PKG-10's
acceptance criteria, and the `windows_installer_roundtrip` `Zone.Identifier` check.

**R2 — The smoke suite silently skips and the merge gate becomes a lie.** Likelihood: medium — three
independent mechanisms can cause it (a `conftest.py` guard typo, an unset `STENOGRAPHER_INTEGRATION`,
an absent model cache) and all three exit 0. Impact: severe — README §D8's gate is the only real
verification this project has for Win32 code, since §P6 forbids the mock alternative. Mitigation: the
skip policy is a single pure function with four unit tests (WIN-PKG-P6, WIN-PKG-01); the collection
guards are asserted in both directions from both OSes and duplicated at the workflow level
(WIN-PKG-07); `BUILD.md` requires reading `-ra` output rather than the exit code (WIN-PKG-09).
Covered by: WIN-PKG-01, WIN-PKG-07, WIN-PKG-09.

**R3 — The Windows bundle ships without PortAudio, or the Linux bundle ships with it.** Likelihood:
medium — `packaging/hook-sounddevice.py` reads as platform-neutral and SCOPE.md §5 predicted it would
carry over, which is exactly wrong (WIN-PKG-P2). Impact: high but loud — the Windows daemon dies at
first `import sounddevice`; a Linux bundle that bundled PortAudio would violate BUILD.md's stated
system-dependency contract. Mitigation: `test_windows_drops_the_local_hook_path` catches the
configuration without a build, and the `build release binary (Windows)` job asserts the DLL is
actually present in the tree. Covered by: WIN-PKG-03, WIN-PKG-05.

**R4 — A Windows provider module touches Win32 at import time and breaks the *Linux* build.**
Likelihood: medium — six other domains are writing `ctypes` modules and a module-level
`from ctypes import wintypes` is a natural thing to write. Impact: high — the Linux release bundle
stops building, and today the failure appears only in `build release binary` on a PR to `main`, far
from the change. Mitigation: WIN-PKG-02 converts it into a fast pure test that runs in the `test` and
`unit-windows` jobs on every PR. Covered by: WIN-PKG-02.

**R5 — The windowed executable breaks worker spawn or shutdown.** Likelihood: medium — under
`stenographerw.exe` there are no stdio handles, so `multiprocessing` spawn relies on its inherited
pipe handle rather than on standard streams, and `SetConsoleCtrlHandler` has no console to register
against. Impact: high — the ASR worker never returns a transcript, or the logon-task daemon cannot be
stopped cleanly. Mitigation: WIN-PKG-P3 states the console-handler consequence explicitly as a
WIN-LIFE requirement rather than leaving it implicit; `windows_bundle_launch` exercises the windowed
executable directly; the frozen worker path already exists on Linux and uses
`get_context("spawn")` on both. Covered by: WIN-PKG-03's smoke case and WIN-PKG-04's step-4 restart
check. Fallback if the windowed executable proves unworkable: ship only the console executable and
accept a console window at logon — a one-line change to `executables("win32")`.

**R6 — The `main` ruleset does not know about the new checks.** Likelihood: high — required check
names are repository settings, not files, and `build.yml` already carries a comment saying the ruleset
requires the exact name `build release binary`. Impact: moderate — `build release binary (Windows)`
and `merge gate` run but do not block, so a broken Windows bundle can reach `main`. Mitigation:
WIN-PKG-05 and WIN-PKG-08 each call out the maintainer settings change by exact check name; it is
listed as a repository-admin action, not a code task. Covered by: the `Done when` statements of
WIN-PKG-05 and WIN-PKG-08, which are only fully satisfied once the checks are required.

**R7 — §D8's third row, read literally, requires two real-machine smoke runs for a documentation
typo.** Likelihood: high — the table's own words are "anything else", and `docs/`, `README.md`,
`LICENSE`, and `.github/` are not in its enumeration. Impact: moderate — friction that pushes
contributors toward attesting without running, which is worse than a narrower rule. Mitigation:
`required_suites()` implements the row literally and fails closed (WIN-PKG-P9) rather than inventing
an exemption, and this risk is the request that the README owner add a documentation-only row to §D8.
Until that amendment lands, the literal table binds. Covered by:
`test_unrecognized_path_fails_closed_to_both`.

**R8 — Release archive round-trip corrupts the bundle.** Likelihood: low — but the failure mode is
quiet. `Compress-Archive` on PowerShell 5.1 writes backslash entry separators, which would make
`sound_asset_guard.py`'s prefix match silently find nothing to validate rather than fail, and
`Get-FileHash` emits uppercase hex that `sha256sum --check` rejects. Impact: high — a published
release asset that does not extract to a runnable tree. Mitigation: WIN-PKG-06 specifies Python-side
zipping and the exact `sha256sum(1)` line format, WIN-PKG-P8 requires the checksum to be re-verified
on a different runner, and `windows_bundle_launch` is re-run against the downloaded zip rather than a
local build. Covered by: WIN-PKG-06.

**R9 — Real-machine merge-gate hardware (SCOPE.md §7 risk 4).** Likelihood: low for this plan —
README §D8 records that a Windows machine is available, which is what makes the gate enforceable.
Impact: severe if it becomes unavailable, since §P6 forbids substituting mocks and the Windows suite
would simply stop running. Mitigation: everything mechanically checkable is pushed into pure tests
that `unit-windows` runs on a GitHub runner (`skip_reason`, collection guards, `spec_support`,
`merge_gate`, provider importability), so hardware loss degrades coverage rather than eliminating it.
Covered by: WIN-PKG-01, WIN-PKG-02, WIN-PKG-03, WIN-PKG-07, WIN-PKG-08.
