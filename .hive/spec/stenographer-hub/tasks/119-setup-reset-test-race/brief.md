# Task: setup-reset-test-race — remove the timing race in the Setup reset test

| Item | Value |
| --- | --- |
| Tier | small |
| Grant | `grants.md 2026-10-20 v0.15.0 rerun and flaky test fix` (merge to `dev` only; no PR to `main`) |

## Overview

`tests/cli/hub/test_setup_doctor.py::test_setup_defaults_replace_config_and_preserve_a_backup`
failed once on the GitHub release runner (draft release run 39508703609):
the saved config still had `audio.input_device = "test microphone"`. It
passes locally and in PR CI. The test presses `shift+d` in Setup, calls one
`pilot.pause()`, leaves `run_test()`, then reads the file. On a slow runner
the reset save has not landed yet.

## Requirements

1. Find how the Setup reset (`shift+d`) saves: synchronously, in a worker,
   after a confirm, or via a message. State it in the evidence.
2. Make the test wait on the saved state, not on time: e.g. await the worker
   or the completion message the app already exposes, or `pilot.wait_for_*`
   on a condition that is true only after the save. No `sleep`, no added
   fixed pauses, no retries.
3. If the race is in the product (the app reports reset done before the file
   is written, or a quit can drop the save), fix the product instead and say
   so; keep the change minimal.
4. Proof the race existed and is gone: make the save path slow
   deterministically in a scratch run (e.g. monkeypatch the save to wait on
   an event) and show the old test fails and the new test passes. Then run
   the test 200 times in a loop (all pass), all hub tests, and the full gate.
5. Change only that test (and product code only under item 3). Conventional
   commit, no trailers, push, `hive task complete`.

Evidence folder: `.hive/spec/stenographer-hub/tasks/119-setup-reset-test-race/evidence/`.

Never signal a process or close a tab, pane or workspace that you did not
start. Never work in workspace wBC (the hive session).
