---
id: FTHR-012
title: Self-diagnosing run stop/run disable error and transcribe --raw
plumage: PLM-005
status: hatching
priority: P2
depends_on: []
authored: 2026-07-15T14:28:16Z
agent: fledge-orchestrate/planning
fledge_version: 0.4.0
---

# FTHR-012: Self-diagnosing run stop/run disable error and transcribe --raw

## Description
Two independent CLI regressions found in a code review of `dev`, both fixed in this feather:
- `stenographer run stop` / `stenographer run disable` (old muscle memory or stale scripts, from before `run`'s nested subcommands were removed) currently hit argparse's generic `unrecognized arguments: stop` at exit 2 — the daemon is NOT stopped and nothing tells the user to use the new top-level command instead (F2).
- `cmd_transcribe` always runs output through `HeuristicFormatter.format_batch(...)`, as collateral fallout from the streaming-rebuild commit; there's no way to get the pre-regression exact verbatim `result.text` for WER benchmarking / diffing (F3).

Both fixes are additive and narrowly scoped: F2 detects the removed invocation before argparse rejects it and emits a pointed error (no nested subcommand restored, no silent alias); F3 adds an opt-in `--raw` flag to `transcribe` that bypasses the formatter, with formatted output staying the default. Satisfies PLM-005 FC-1 (F2), FC-2/FC-3 (F3), FC-4 (README).

## Affected Modules
Per `.fledge/nest/entry-points.md` (CLI dispatch — `main()`, `cmd_transcribe`) and `.fledge/nest/modules.md` (`_parser.py` kept import-light for the argcomplete hot path):
- `src/stenographer/cli.py` — `main()` (new pre-parse check, F2) and `cmd_transcribe` (new `raw` parameter, F3).
- `src/stenographer/_parser.py` — `transcribe` subparser gains `--raw` (F3).
- `README.md` — the `transcribe` line under `## Run` (F3, FC-4).
- `tests/test_cli.py` — new tests for both fixes (this file already imports `stenographer.cli as cli` and exercises its module-level helpers directly).

## Approach
- **F2** in `main()`: before `args = parser.parse_args(argv)`, normalize `argv_list = list(argv) if argv is not None else sys.argv[1:]` and scan it for `"run"` immediately followed by `"stop"` or `"disable"` as the next element (adjacent-token check — covers `stenographer run stop` and `stenographer -c foo.toml run stop`; a flag interposed between `run` and `stop` is out of scope, matching the plumage's narrow framing). If found, print `f"stenographer: \`run {replacement}\` was removed; use \`stenographer {replacement}\` instead."` to stderr (where `replacement` is `stop` or `disable`) and return `1` — no argparse invocation happens for this path, so the daemon-not-stopped state is reported immediately and distinctly from argparse's generic message. `run` itself keeps taking no arguments; no nested subparser is added back.
- **F3** in `_parser.py`: add `transcribe.add_argument("--raw", action="store_true", help="Emit the raw ASR transcript, unformatted.")`.
- **F3** in `cli.py`: `cmd_transcribe(cfg: Config, path: pathlib.Path, *, raw: bool) -> int` — after `result = model.transcribe(...)`, branch: if `raw`, `text = result.text`; else the existing `HeuristicFormatter(...).format_batch(result.segments)` path, unchanged. Same `sys.stdout.write(text); sys.stdout.write("\n")` tail for both. Update the `args.subcommand == "transcribe"` dispatch line in `main()` to pass `raw=args.raw`.
- **F3** in `README.md`: replace the single `stenographer transcribe FILE     # batch: print transcript to stdout` line with two lines documenting the default (formatted) behavior and `--raw` (verbatim), matching the surrounding list's style.
- No change to `HeuristicFormatter`, `dictate`/`live`/streaming output paths, or any other subcommand's argument surface.

## Tests
All in `tests/test_cli.py`:
- `test_run_stop_names_stop_replacement` — `cli.main(["run", "stop"])` returns nonzero; captured stderr (via `capsys`) contains `"stenographer stop"` and does not match argparse's generic `"unrecognized arguments"` text.
- `test_run_disable_names_disable_replacement` — same for `cli.main(["run", "disable"])`, asserting stderr names `"stenographer disable"`.
- `test_run_alone_still_dispatches_normally` — a regression guard: `build_parser().parse_args(["run"])` still parses with `subcommand == "run"` and no error (confirms the F2 scan doesn't false-positive on bare `run`).
- `test_transcribe_default_output_is_formatted` — call `cli.cmd_transcribe(cfg, path, raw=False)` (or exercise via `cli.main`) with `Model.transcribe` mocked/monkeypatched to return a known raw-ish `TranscriptionResult` (e.g. text `"i think so"` with a matching segment), assert captured stdout is capitalized/spacing-normalized (mirrors existing `HeuristicFormatter` output conventions used elsewhere in the test suite).
- `test_transcribe_raw_flag_emits_verbatim_text` — same fixture, `raw=True`, assert captured stdout equals `result.text` exactly (e.g. still lowercase `"i think so"`, unformatted).
- `test_parser_accepts_transcribe_raw_flag` — `build_parser().parse_args(["transcribe", "f.wav", "--raw"]).raw is True`; `build_parser().parse_args(["transcribe", "f.wav"]).raw is False` (default off).

Implementation order: write all six tests, run against the unchanged code and confirm they FAIL for the expected reason (the two `run` tests fail because argparse's generic message/exit-2-without-daemon-context is what's observed instead of the pointed one; the raw-flag parser test fails with `AttributeError`/`unrecognized arguments --raw`; the two transcribe-output tests fail because `cmd_transcribe` has no `raw` parameter at all), then implement F2 and F3 until all pass. Update the README line as part of the same change (not test-driven, but required by FC-4).

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `stenographer run stop` / `stenographer run disable` exit nonzero with stderr naming the correct replacement command, distinguishable from argparse's generic "unrecognized arguments" message; `run` continues to take no arguments and no nested subcommand is restored (satisfies PLM-005 FC-1).
- [x] AC-3: `stenographer transcribe FILE` (no flag) continues to emit `HeuristicFormatter`-formatted output, unchanged from today (satisfies PLM-005 FC-2).
- [x] AC-4: `stenographer transcribe FILE --raw` emits `result.text` verbatim (satisfies PLM-005 FC-3).
- [x] AC-5: The README's `transcribe` entry documents both the default formatted output and `--raw` (satisfies PLM-005 FC-4).
- [x] AC-6: `.venv/bin/pytest -m "not integration"` passes with no regressions.
