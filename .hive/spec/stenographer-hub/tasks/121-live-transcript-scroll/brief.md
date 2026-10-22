# Task: live-transcript-scroll — scroll within the live transcript

| Item | Value |
| --- | --- |
| Tier | decent |
| Goal | `g2-live-scroll` (user chat c7, 2026-10-22: scroll within the stenographer live view; land on `dev`) |
| Grant | coordinator inbox record 195: implement and land on `dev` only; no PR to `main` |

## Overview

The user wants to scroll the live transcript. Two surfaces show it:

- Hub Live section: `src/stenographer/cli/hub/live_view.py`. `#live-transcript`
  is one `Static` (CSS in `cli/hub/app.py`, `overflow-y: auto`). `refresh_view`
  runs every 0.1 s and replaces its whole content. Long sessions are clipped;
  the user cannot reach older or newer lines.
- Standalone app: `src/stenographer/cli/live/app.py` (`LiveApp`). The
  transcript `Static` sits in a `VerticalScroll`, but nothing keeps the newest
  line in view and no keys scroll it.

## Design

| Board | Source | PNG |
| --- | --- | --- |
| StenoB | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/StenoB.dc.html` | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/StenoB.png` |
| LiveSplit | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer/LiveSplit.dc.html` | `/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/LiveSplit.png` |

These are the approved hub Live boards (mixed and split). Scrolling must not
change the layout: the hub Live screen must still match both boards. Capture
the hub Live screen in mixed and split view, at the bottom and scrolled up,
and compare with the boards per the visual-check rule. Two allowed
differences, to record as `overridden` with cause "goal g2-live-scroll (user
chat c7)": (a) the added scroll keys in the Live key hints, (b) the thin
accent scrollbar that docs/hub.md already allows when content overflows.
The standalone `stenographer live` app (`cli/live/app.py`) has no board:
change only its key hint text there, and capture it before and after.

## Requirements

1. Make the transcript scrollable on both surfaces, in mixed and split view.
2. Input:
   - Mouse wheel scrolls the transcript.
   - Keys: `up`/`down` (one line), `pageup`/`pagedown` (one page),
     `home`/`end` (top/bottom). In the hub these act only while the Live
     section is shown; they must not change Config, Files, Sessions, Setup or
     Doctor behavior (hub `up`/`down` are app bindings today: route them by
     section, do not break the other sections). If a key truly conflicts,
     stop and report to the manager before picking another key.
3. Follow at bottom: while the view is at the bottom, new lines keep the
   newest line in view. Once the user scrolls up, new lines and the 0.1 s
   refresh must not move the view. Scrolling back to the bottom (or `end`)
   resumes following. A session start shows the bottom.
4. The 0.1 s refresh must not reset the scroll position or flicker. Do not
   rebuild more than today unless needed for this.
5. Show the new keys in the Live key hints of both surfaces, kept short.
   Update `docs/live.md`, `docs/hub.md`, README and the Pages site (`site/`)
   where they list live keys.
6. Tests (Textual `run_test` pilot, no microphone, no real audio; use a fake
   session like the existing hub/live tests): wheel or key scroll moves the
   view; scrolled-up view stays put when lines are added; `end` or reaching
   the bottom resumes follow; new lines while at bottom stay visible; hub
   `up`/`down` still move Config keys in Config. Show each new test fails with
   the feature stubbed out, then passes.
7. Run the full gate from AGENTS.md (ruff check, ruff format --check, pytest
   -m "not integration", stenographer --help). Conventional commit(s), no
   attribution trailers, push the task branch, `hive task complete`.

Evidence folder: `.hive/spec/stenographer-hub/tasks/<task id>/evidence/`.
Record: the scroll design, the fail-then-pass proof, and the gate output.

Never signal a process or close a tab, pane or workspace that you did not
start. Never work in workspace wBC (the hive session). Never access the
microphone.
