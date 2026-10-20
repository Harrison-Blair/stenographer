# 54-remove-windows verification

Verifier: independent re-run on 2026-10-19 against `a4034d4` (implementation
`412edd4`, base `8fa9459`). The worktree has no `.venv`, so
`/home/penguin/source/stenographer/.venv` was used with `PYTHONPATH=src`
(confirmed `stenographer.__file__` resolves to this worktree).

| Item | Result | Observation |
| --- | --- | --- |
| V1 platform removal | pass | Six provider files deleted (`git diff --name-status` shows `D` for each); both factories select only Linux and raise `UnsupportedPlatformError`; `Platform` protocol remains. |
| V2 Windows-specific guards | **fail** | V2 states no Windows-only guards remain, but extra Windows-only branches are left and were not reported (see below). |
| V3 config compatibility | pass | CRLF legacy config loads: `binding=KEY_RIGHTALT`, `general_binding=KEY_RIGHTCTRL`; migration kept, docstring reworded. |
| V4 Linux coverage review | pass | Per-change reasons are present; removed test diffs checked (e.g. `test_persistence.py` guards removed, tests now run unguarded on Linux). |
| V5 regression test | pass | Red at base (fresh base worktree + new tests): `2 failed`, `DID NOT RAISE UnsupportedPlatformError`. Green on task: `2 passed`. |
| V6 keycodes | pass | `gen_keycodes.py --check`: up to date; `KEY_CYCLEWINDOWS` is a Linux evdev name. |
| V7 CI | pass (with leftover, see V2) | `unit (windows)` job and `windows-latest` entry removed; all workflow YAML parses; `lint`, `test`, `build release binary` names intact. |
| V8 diff report | pass | `git diff --shortstat 8fa9459 412edd4`: `41 files changed, 127 insertions(+), 775 deletions(-)`, matches report. |
| V9 gate | pass | ruff check: All checks passed; ruff format: 569 files already formatted; pytest: 2538 passed, 2 skipped, 6 deselected; `stenographer --help` exit 0. |

## V2 differences

Requirement 1 asks to remove every branch that selects Windows and the
Windows-only test guards, with no empty branches. Requirement in the brief:
"Grep again yourself and report every extra hit." These remain and are not in
`report.md`:

1. `.github/workflows/native.yml`: matrix key `exe: ''` and its three uses
   `stenographer${{ matrix.exe }}` (lines 25, 53-55) existed only for the
   Windows `.exe` suffix; `if: runner.os == 'Linux'` (line 39) is now always
   true. The `python`/`pip` matrix keys likewise only existed to switch to
   `.venv/Scripts/*.exe`.
2. `os.name != "posix"` / `os.name == "posix"` test guards, the same kind the
   worker removed from `test_persistence.py` as Windows-only:
   - `tests/lib/config/test_document.py:268` (skipif)
   - `tests/lib/live/test_session_writer.py:59,78,126,152` (conditional asserts)
   - `tests/overlay/platform/linux/test_backend_base.py:233` (skip)
   - `tests/test_release_preflight_workflow.py:12` (module skipif)

Found with:

```sh
git grep -n -E 'msvcrt|winreg|windll|pywin32|os\.name|APPDATA|\.exe\b|sys_platform' -- ':!docs/reference/guru/**' ':!evidence/**'
```

Verdict: fail. Either remove these or record in the evidence why each one stays.

# Re-verification after repair

Verifier: independent re-run on 2026-10-19 against `51d5af2` (implementation
`412edd4`, repair `51d5af2`, base `8fa9459`). The worktree has no `.venv`, so
`/home/penguin/source/stenographer/.venv` was used with `PYTHONPATH=src`
(`stenographer.__file__` resolves to this worktree).

| Item | Result | Observation |
| --- | --- | --- |
| V1 platform removal | pass | `git diff --name-status 8fa9459 HEAD` shows `D` for the six provider files; both factories select only Linux and raise `UnsupportedPlatformError`; `class Platform(Protocol)` remains in `platform.py`. |
| V2 Windows-specific guards | pass | The V2 `rg` search has no hits (exit 1). The earlier FAIL items are fixed: `native.yml` has no `exe`/`python`/`pip` matrix keys and no `runner.os` condition; the `os.name` guards in the four named test files are removed with their assertions kept. The wide `git grep` (`os.name`, `sys.platform`, `platform.system`, `win32`, `nt`, `.exe`, `runner.os`) shows exactly the hits listed in V2.md. A `msvcrt`/`winreg`/`windll`/`pywin32`/`APPDATA`/`.exe` grep shows only Linux `sys_platform` markers in `pyproject.toml`. The `windows|win32` grep matches the list in `report.md`. |
| V3 config compatibility | pass | CRLF legacy config script prints `CRLF legacy hotkey config loads; Right Alt Agent binding is preserved`; migration kept, docstring reworded only. |
| V4 Linux coverage review | pass | Reasons present for each change; repair diffs checked: the `os.name` conditionals became unconditional assertions, and the skips were removed, so Linux runs the same or more assertions. |
| V5 regression test | pass | Red: fresh base worktree at `8fa9459` with the two task test files: `2 failed`. Green on task: `2 passed`. |
| V6 keycodes | pass | `gen_keycodes.py --check`: `keycodes up to date`. |
| V7 CI | pass | All seven workflow YAML files parse with PyYAML; `unit (windows)` and `windows-latest` absent; `test`, `lint`, `build release binary` job names present. No workflow was run. |
| V8 diff report | pass | `git diff --shortstat 8fa9459 412edd4`: `41 files changed, 127 insertions(+), 775 deletions(-)`, matches `report.md`. Note: `report.md` covers only `412edd4`; the full branch without evidence and `VERIFIED.md` is `45 files changed, 138 insertions(+), 803 deletions(-)` (repair adds `native.yml` and four test files, listed in V2.md). |
| V9 gate | pass | ruff check: `All checks passed!`; ruff format: `569 files already formatted`; pytest: `2538 passed, 2 skipped, 6 deselected`; `stenographer --help` exit 0. |

Verdict: pass. Integration tests, microphone, live, models, and workflows were
not used. The temporary base worktree was removed.
