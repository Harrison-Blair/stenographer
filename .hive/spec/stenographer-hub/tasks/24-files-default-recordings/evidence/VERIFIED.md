# Verification — 24-files-default-recordings

Verdict: **pass**. Verified commit: `566a26e`. Base: `f5a0fc8`.

All checks ran again from the task worktree. The brief now includes the user design waiver dated 2026-10-21. Independent before/after captures meet that waiver. No source file, V<n>.md file, or plan tracker was changed.

## Items

| Item | Result | Observation |
| --- | --- | --- |
| 1. Recordings default and XDG_DATA_HOME | pass | Real HubServices and the current platform open Files in synthetic data/stenographer/sessions. |
| 2. Missing or non-directory fallback | pass | Regression checks home fallback without creating sessions. A separate mounted-app check used a regular file at sessions: Files opened home and preserved the file. |
| 3. Parent navigation and title | pass | Pilot up/enter navigates to sessions.parent. Regression asserts the absolute sessions path as the browser border title outside home. Long paths use the existing visual ellipsis. |
| 4. Output default | pass | Service output stays data/stenographer/files; standalone panel output stays home/.local/share/stenographer/files. Both captures show the same output destination. |
| 5. Failing-first tests | pass | Base: 2 failed, 1 passed. Broken missing-folder fallback: 1 failed, 2 passed. Broken output default: 1 failed, 2 passed. Restored Files suite: 22 passed in 13.02s. |
| 6. Documentation | pass | Reviewed README.md, docs/hub.md, and site/index.html diffs. All describe the recordings default. Owning docs include missing-folder fallback and parent navigation. |
| 7. Fresh before/after evidence | pass | Replaced verifier-before-files.svg/.txt/.png and verifier-after-files.svg/.txt/.png with independent captures. Synthetic folders only; no audio or transcript content. |
| Design waiver and plain-text states | pass | Applied the explicit waiver in the Design section. Both PNGs inspected; changed screen states have text or glyphs. See table below. |
| Ruff check | pass | `.venv/bin/ruff check .`: All checks passed! |
| Ruff format | pass | `.venv/bin/ruff format --check .`: 749 files already formatted. |
| Non-integration suite | pass | `.venv/bin/pytest -m "not integration"`: 2697 passed, 2 skipped, 6 deselected in 145.77s. Skips: absent Silero model and public speaker clips. |
| CLI help | pass | `.venv/bin/stenographer --help`: exit 0; expected command list displayed. |

The task specifies a Python gate. The generic skill's Go gate does not apply.

## Red and green runs

For each isolated source variant, ran:

```sh
PYTHONPATH="$PWD/.hive/tmp/reverify24/VARIANT/src" .venv/bin/pytest tests/cli/hub/test_files.py -k 'recordings_folder or ignores_start' -q
```

- `base`: `git archive f5a0fc8 src`. Recordings default fails because it opens home. Standalone output test fails because the old panel lacks the start argument. Missing-folder test passes because base always opens home.
- `no-fallback`: current source with `self.directory = start`. Missing-folder test fails on its directory assertion.
- `wrong-output`: current source with output fallback derived from self.directory. Output-folder assertion fails.
- Unchanged current source: `.venv/bin/pytest tests/cli/hub/test_files.py -q`: 22 passed.

Full red outputs: verifier-red-base.txt, verifier-red-no-fallback.txt, verifier-red-wrong-output.txt. Full gate test output: verifier-gate-pytest.txt. Production source was never edited.

## Visual check

Ran independent base and current HubApp pilot sessions at 150 by 45. Each used `app.save_screenshot()` plus FilesPanel.display_text(). Converted both SVGs to PNG with headless Firefox using separate scratch profiles; rsvg-convert is unavailable. Initial Firefox calls failed because profile directories did not exist. Created those directories and reran successfully.

The Design section waives the approved board for this task. The table compares the fresh before and after captures. `overridden` records the change approved by the brief.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| Browser title | ~ before; absolute path after | overridden | User requires the recordings folder; full model title verified. Existing truncation applies to this long scratch path. |
| Browser rows | ../, names ending /, selected-row ▶ | overridden | Before shows Music/. After shows two synthetic session folders. This is the requested default change. |
| Navigation | ▶ 2 Files | matches | Selection has a glyph and a word. |
| Options | [x] diarize; [ ] cleanup pass; count auto | matches | Checkbox state remains visible without colour. |
| Output | md · jsonl · srt · txt; save to .../files | matches | Output destination is identical in both renders. |
| Queue | No queued jobs. | matches | Empty state has plain text. |
| Preview | Queue a file to preview its transcript. | matches | Empty state has plain text. |
| Sidebar and controls | engine; cpu; 0%; named keys | matches | Layout and labels are unchanged. |

Plain-text Files captures contain no colour codes. Folder selection, checkbox states, and empty states remain identifiable. PNGs show the same layout before and after. No new colour-only state was found. Queued and completed jobs were outside this change.

## Limits and cleanup

No microphone, recording command, model download, integration test, real-machine acceptance, or reinstall ran. The manager can offer `scripts/reinstall.sh` to the user; this verification does not authorize it. Removed the isolated source copies, render script, synthetic folders, and Firefox profiles after recording the results. Final evidence remains in this task's evidence folder.
