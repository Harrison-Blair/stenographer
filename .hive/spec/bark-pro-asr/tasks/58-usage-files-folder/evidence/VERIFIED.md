# Independent verification — task 58-usage-files-folder

Verdict: pass. Reviewed worker HEAD `1a7a694c4ae0aa0091a71b26966beb284206f5f7`.

| Item | Result | Observation |
| --- | --- | --- |
| Correct the sentence only | pass | An independent Python comparison against `git show origin/dev:docs/usage.md` confirmed that only the requested sentence changes after whitespace normalization. The other text is unchanged. The relative link resolves to `docs/hub.md`. |
| Check the code and hub guide | pass | `services.py:114-115` selects the platform data directory plus `sessions`. `services.py:85-88` uses that same path for the Live session store. `app.py:301` passes the start folder to Files. `files_view.py:103-107` uses the home folder when the start folder is not a directory. `docs/hub.md:97-102` describes this behavior. |
| Source commit | pass | `git show -s --format=full a6e5949` shows the required subject `docs(usage): say Files opens in the recordings folder` and no trailers. |
| Separate V1 evidence commit | pass | Read V1 without editing it. It contains the diff, code references, and changed-file list. `git show --format=full --stat 1a7a694` confirms a separate evidence-only commit. |
| Change scope | pass | `git diff --name-only origin/dev...HEAD` lists only `docs/usage.md`, this task's brief, and its V1 evidence. No other project files changed. |
| Task branch pushed and task complete | pass | `git ls-remote origin refs/heads/task/58-usage-files-folder` matches worker HEAD. `hive task show 58-usage-files-folder` reports `status: completed`. |

## Additional check

`git diff --check origin/dev...HEAD -- docs/usage.md` passes. The full diff check reports two trailing-whitespace lines in V1's embedded diff (lines 13 and 24). These are blank context lines copied from the patch. They do not affect the requested document or its meaning. V1 was not changed.

This is a documentation-only task. The brief specifies no test, live, UI, or code gate item. No venv was created, and no integration test or microphone access was used. No application behavior was changed or exercised at runtime.
