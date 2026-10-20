# 40-remove-macos verification

| Item | Value |
| --- | --- |
| Task | 40-remove-macos |
| Verified commit | 04ea0cb (implementation 8d32520, base 4b8f12f) |
| Date | 2026-10-19 |
| Agent | verifier, Claude Code, claude-opus-5-5 |
| Environment | No worktree `.venv`; used `/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=src`, as the worker did. |

| Item | Proves | Result | Observation |
| --- | --- | --- | --- |
| V1 | R1 | pass | `git grep -n -i -E 'macos\|darwin\|osx\|apple\|\bmac\b'` (excluding guru and evidence) gives the same 8 hits as V1: CHANGELOG entry, `-apple-system` font in `site/site.css`, and the two new regression tests. `rg 'darwin\|macos\|platform\.macos' src scripts` finds nothing. `lib/platform/` and `overlay/platform/` hold only `linux` and `windows` provider packages. |
| V2 | R2 | pass | Red: in a temporary worktree at base 4b8f12f with the two HEAD test files copied in, both new tests fail with pytest.raises failures (`2 failed`, exit 1). Green: at HEAD, `2 passed`, exit 0. Diff review: the Windows overlay and system-audio cases keep their assertions, the Linux and Windows dispatch rows remain, and the network-guard change only rewords the docstring. |
| V3 | R3 | pass | Only `.github/workflows/native.yml` changed under `.github/workflows/`. The diff removes only the `macos-15-intel` and `macos-15` entries; the `ubuntu-24.04` and `windows-latest` entries remain. `yaml.safe_load` parses every workflow file. `rg -i 'macos\|darwin\|osx\|\bmac\b' README.md site` finds nothing. The AGENTS.md diff is the single line 14 change. |
| V4 | R4 | pass | `git diff --shortstat 4b8f12f 8d32520` gives `23 files changed, 56 insertions(+), 442 deletions(-)`, which matches report.md. `--diff-filter=D` lists the same six deleted files as report.md. |
| V5 | Gate | pass | `ruff check .`: All checks passed (exit 0). `ruff format --check .`: 575 files already formatted (exit 0). `pytest -m "not integration"`: 2545 passed, 2 skipped (absent audio samples), 6 deselected (exit 0). `stenographer --help`: prints usage (exit 0). |

## Notes

- The V2 coverage table names the two Windows overlay tests by their old
  names (`test_a_host_without_an_overlay_*`). The commit renamed them to
  `test_windows_without_an_overlay_refuses_to_spawn_a_helper` and
  `test_windows_without_an_overlay_still_explains_itself_to_doctor`. The
  assertions are unchanged. This is an evidence wording slip and does not
  change a result.
- The temporary base worktree was removed after the red run.
