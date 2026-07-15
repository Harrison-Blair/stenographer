---
id: PLM-005
title: CLI regressions (dictate/transcribe surface)
status: fledged
priority: P2
authored: 2026-07-15T05:05:29Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# PLM-005: CLI regressions (dictate/transcribe surface)

## Context
A code review of the current `dev` branch found two CLI regressions unrelated to prompt mode:

1. `run` used to be a subcommand with its own nested subparsers (`run stop`, `run disable`); a deliberate refactor replaced these with top-level `stop`/`disable` commands and the README was updated to match (it now documents only `stenographer stop` / `stenographer disable`, with no mention of the old nested form). But `stenographer run stop` / `stenographer run disable` still hit argparse's generic `unrecognized arguments: stop`, exit 2, and — critically — the daemon is NOT stopped, with no message connecting the failure to "use `stenographer stop` instead." Someone still on old muscle memory or a stale script can walk away believing they killed the daemon when they didn't.
2. `cmd_transcribe` used to emit `result.text` (the ASR model's raw, unmodified output) verbatim to stdout. As collateral fallout from the streaming-rebuild commit (confirmed via `git log -S`, not a deliberate decision about `transcribe` specifically), it now always runs output through `HeuristicFormatter.format_batch(result.segments)` — capitalization, spacing normalization, and pause-based paragraph breaks if configured. Scripts or diffs that depended on exact recognized text (e.g. WER benchmarking, regression comparisons) now get silently altered output with no way to opt out.

This plumage makes the `run stop`/`run disable` failure self-diagnosing (without resurrecting the removed subcommand form) and adds a `--raw` flag to `transcribe` so exact verbatim ASR output remains available on demand, while formatted output stays the default.

## User Stories
- As a user who types `stenographer run stop` out of habit, I want a clear error telling me the daemon wasn't stopped and to use `stenographer stop` instead, rather than a generic argparse error that leaves me unsure whether the daemon is still running.
- As a user or script that needs the exact, unaltered ASR transcript from `stenographer transcribe FILE` (e.g. for WER benchmarking or diffing against a reference), I want a `--raw` flag that emits `result.text` verbatim, so I'm not stuck with formatter-altered text.
- As a user reading the README's `transcribe` documentation, I want it to state both the default (formatted) output and the `--raw` (verbatim) option, so the command's behavior is fully documented.

## Functional Criteria
1. FC-1: Invoking `stenographer run stop` or `stenographer run disable` exits nonzero with a pointed error message naming the correct replacement command (`stenographer stop` / `stenographer disable` respectively) — distinguishable from argparse's generic "unrecognized arguments" message. No nested `run` subcommand is restored; `run` itself continues to take no arguments.
2. FC-2: `stenographer transcribe FILE` (no flag) continues to emit output through `HeuristicFormatter.format_batch(result.segments)`, exactly as it does today — this is now the documented, intentional default.
3. FC-3: `stenographer transcribe FILE --raw` emits `result.text` verbatim (unformatted), restoring the pre-regression exact-transcript behavior.
4. FC-4: The README's `transcribe` entry documents both the default formatted output and the `--raw` verbatim option.

## Acceptance Criteria
- [x] AC-1: A test demonstrates that `stenographer run stop` exits nonzero and its stderr names `stenographer stop` as the replacement (not argparse's generic "unrecognized arguments" text).
- [x] AC-2: A test demonstrates the same for `stenographer run disable` naming `stenographer disable`.
- [x] AC-3: A test demonstrates that `stenographer transcribe FILE` (no flag) on a known input produces `HeuristicFormatter`-formatted output (e.g. capitalized/spacing-normalized), matching today's behavior.
- [x] AC-4: A test demonstrates that `stenographer transcribe FILE --raw` on the same input produces the exact verbatim `result.text`, unaltered by the formatter.
- [x] AC-5: The README's `transcribe` line/section documents both the default formatted behavior and `--raw`.
- [x] AC-6: The full unit test suite (`.venv/bin/pytest -m "not integration"`) passes with no regressions to existing CLI behavior.

## Out of Scope
- Restoring the removed `run stop`/`run disable` nested subcommands, or any deprecated-alias forwarding that silently makes them work again.
- Adding a `--raw` (or equivalent) flag to `dictate` or any live/streaming output path — scoped only to the batch `transcribe` command.
- Any change to `HeuristicFormatter`'s own behavior (spacing/capitalization/paragraph logic) — only which output path `cmd_transcribe` uses by default vs. under `--raw`.
- Any other CLI subcommand's argument surface beyond `run`'s failure mode and `transcribe`'s new `--raw` flag.

## Open Questions
None — resolved during interrogation: F2 is a pointed, self-diagnosing hard error (no restored subcommand, no silent alias); F3 keeps formatted output as the default and adds `--raw` for verbatim output, with a corresponding README update; priority P2.
