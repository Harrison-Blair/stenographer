# Task: delete-fixmd — remove the temporary FIX.md

| Item | Value |
| --- | --- |
| Tier | small |
| Feature | bark-pro-asr |
| Base | origin/dev 7b4700f (includes the user's encoder-pin fix) |

## Overview

Both machines ran the FIX.md handoff (user, 2026-10-22). Delete `FIX.md` in its own
commit. Remove only the references its deletion leaves stale. On origin/dev 7b4700f
these are:

- `.gitignore` line `!/FIX.md`
- `pyproject.toml` line `"!/FIX.md",` and the comment line directly above it
  (`# Temporary Bark Pro handoff prompt; a later commit deletes it.`)

Check with `git grep -n 'FIX\.md' -- . ':!.hive'` after the change: it must find
nothing. README, docs, site and CHANGELOG have no FIX.md link; change nothing else.
Leave `.hive/` history (spec, briefs, evidence) as it is.

## Steps

1. Confirm your branch contains 7b4700f (`git merge-base --is-ancestor 7b4700f HEAD`).
   If not, stop and tell the manager through the inbox.
2. Delete `FIX.md` and the three lines above. One commit:
   `chore: delete the temporary FIX.md handoff`.
3. Evidence in `.hive/spec/bark-pro-asr/tasks/55-delete-fixmd/evidence/V1.md` (separate
   commit, `git add -f`): the grep result, `git show --stat` of the commit, and the
   gate output.
4. Push the task branch and run `hive task complete`.

## Rules

- Never run any git stash command (stash@{0} is the user's WIP). Never run sudo.
- Do not push dev or main, open a PR, or run a workflow. Conventional commits, no
  attribution trailers.
- Never signal a process or close a pane you did not start. Never work in wBC.
- Gate: no Python changes, so no venv is needed (never create one). Run
  `git diff --name-only origin/dev...HEAD` and show it lists only `FIX.md`,
  `.gitignore`, `pyproject.toml` and this task's `.hive/` files. If a `.venv` exists
  in the worktree, also run `.venv/bin/ruff check .`; otherwise say it was skipped.
