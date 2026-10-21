# Verification — 24-files-default-recordings

Verdict: **fail**. The implementation checks pass. The brief has no `Design` section and no absolute path to an approved board. The verifier skill requires both for a UI change. An approved-board comparison is therefore incomplete.

Verified commit: `cc9ffde`. Base: `f5a0fc8`. All commands ran from the task worktree. Only synthetic folders were used. No microphone, audio capture, model download, integration test, or real-machine acceptance ran.

## Items

| Item | Result | Observation |
| --- | --- | --- |
| 1. Start in platform data directory; respect XDG_DATA_HOME | pass | Real HubServices and platform: Files opens in the temporary data/stenographer/sessions folder. |
| 2. Fall back to home; do not create sessions | pass | Missing-folder regression passes. A separate mounted-app check with a regular file at sessions also falls back to home and preserves the file. |
| 3. Parent navigation and external-home title | pass | Pilot up/enter moves to sessions.parent. Browser title is the absolute sessions path outside home. |
| 4. Output-folder default | pass | Service output remains data/stenographer/files. Standalone panel fallback remains home/.local/share/stenographer/files. |
| 5. Failing-first and mutation checks | pass | Base: 2 failed, 1 passed. Broken fallback: 1 failed, 2 passed. Broken output default: 1 failed, 2 passed. Restored implementation: 3 passed. See details below. |
| 6. Documentation | pass | Reviewed README.md, docs/hub.md, and site/index.html diffs. All describe the new default; owning docs describe fallback and parent navigation. |
| 7. Before/after synthetic renders | pass | Independently captured verifier-before-files.svg/.txt and verifier-after-files.svg/.txt. Before opens home and lists Music/. After lists two empty session folders. Both show the same output folder. PNG captures are included. |
| Visual approval | fail | No Design section or approved board path in the brief. Cannot capture an approved board or compare its elements. |
| Ruff check | pass | `.venv/bin/ruff check .`: All checks passed! |
| Ruff format | pass | `.venv/bin/ruff format --check .`: exit 0; initial run reported 748 files already formatted. After scratch cleanup, a second run reported 749 files already formatted. Both checks passed. |
| Non-integration suite | pass | `.venv/bin/pytest -m "not integration"`: 2697 passed, 2 skipped, 6 deselected in 151.28s. Skips: absent Silero VAD model and public speaker clips. |
| CLI help | pass | `.venv/bin/stenographer --help`: exit 0; existing subcommands listed. |

The repository is Python. Its brief specifies the four commands above; the Go gate in the generic verifier skill does not apply.

## Regression reruns

Exact regression command:

```sh
.venv/bin/pytest tests/cli/hub/test_files.py -k "recordings_folder or ignores_start" -q
```

The base and mutation runs used isolated source copies under `.hive/tmp/verify-24/`, selected with `PYTHONPATH`. No production source was edited.

- Base source from `git archive HEAD^ src`: start-folder assertion fails because directory is home; standalone output test fails because the base has no start argument. The missing-folder test passes because base always opens home.
- Current source with fallback deliberately changed to `self.directory = start`: missing-folder assertion fails.
- Current source with standalone output fallback deliberately derived from self.directory: output-folder assertion fails.
- Current, unchanged source: 3 passed, 19 deselected.
- `.venv/bin/pytest tests/cli/hub/test_files.py -q`: 22 passed.

Full red-run output is retained in verifier-red-base.txt, verifier-red-no-fallback.txt, and verifier-red-wrong-output.txt.

## Visual check

The new screen and base screen were captured with `app.save_screenshot()` at 150 by 45. Firefox rendered each SVG to a PNG because `rsvg-convert` is unavailable. The system Rsvg Python binding also could not render a Cairo context. The after PNG was inspected. Its browser title, session rows, output folder, queue, and preview are visible without clipping at this test size.

No approved board is named, so the following rows describe the inspected screen. They do not claim agreement with an approved board.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| Browser title | absolute sessions path | differs | Approved board unavailable; the path agrees with requirement 3. |
| Browser rows | ../, folder names with /, selected-row glyph ▶ | differs | Approved board unavailable; synthetic sessions replace the base Music folder. |
| Files navigation | ▶ and 2 Files | differs | Approved board unavailable; selection has a glyph without colour. |
| Options | [x] diarize, [ ] cleanup pass, count auto | differs | Approved board unavailable; checkbox states have text glyphs. |
| Output destination | save to .../data/stenographer/files | differs | Approved board unavailable; destination is unchanged between captures. |
| Queue | No queued jobs. | differs | Approved board unavailable; empty state has plain text. |
| Preview | Queue a file to preview its transcript. | differs | Approved board unavailable; empty state has plain text. |

Plain text was checked without colour in verifier-after-files.txt. Browser selection, folder rows, checkbox states, and queue/preview empty states remain identifiable. No new colour-only state was found. No queued or completed job state was exercised by this task.

## Limits and cleanup

Real-machine acceptance and reinstall were not run. This verification does not authorize either. All temporary source copies, scripts, synthetic folders, and Firefox profile were removed after recording the results. Final evidence remains in this folder. No V<n>.md file or plan tracker was changed.
