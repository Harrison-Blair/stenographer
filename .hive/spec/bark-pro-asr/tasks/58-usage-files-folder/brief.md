# Task: usage-files-folder — fix the Files start folder in docs/usage.md

| Item | Value |
| --- | --- |
| Tier | small |
| Feature | bark-pro-asr (release v0.16.0 preparation) |
| Base | origin/dev 32f7806 |

## Overview

`docs/usage.md` line 227 says "The browser starts in your home folder." Since cc9ffde
the hub Files browser opens in the folder where Live saves recordings and falls back
to your home folder only when that folder does not exist yet. `docs/hub.md` (around
lines 95-101), README and `site/index.html` already say this. Fix only that sentence
in `docs/usage.md` so it matches `docs/hub.md`, in the file's plain second-person
style. You may link to `docs/hub.md` instead of repeating the paths. Change nothing else.

## Steps

1. Edit the sentence. Check the behaviour in the code (the hub Files browser start
   folder) so the wording is true.
2. Commit `docs(usage): say Files opens in the recordings folder`, no trailers.
3. Evidence `.hive/spec/bark-pro-asr/tasks/58-usage-files-folder/evidence/V1.md` (separate commit,
   `git add -f`): the diff, the code line that sets the start folder, and
   `git diff --name-only origin/dev...HEAD` listing only `docs/usage.md` and this
   task's `.hive/` files.
4. Push the task branch and run `hive task complete`.

## Rules

- Docs only; no venv is needed. Never create a venv.
- Never run any git stash command (stash@{0} is the user's WIP). Never run sudo.
- Do not push dev or main, open a PR, run a workflow, or touch tags.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Ask questions through `hive inbox send --to manager-stenographer`.
