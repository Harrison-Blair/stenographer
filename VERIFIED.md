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
