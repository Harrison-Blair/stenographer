# VERIFIED — 111-hub-config-board

Verifier: independent agent (claude-verifier), 2026-10-20, branch head `d610993`.
Base: `d8ad650`. The worktree has no `.venv`; every command used
`/home/penguin/source/stenographer/.venv/bin/` with `PYTHONPATH=$PWD/src`
(checked: `stenographer.__file__` resolves to this worktree's `src/`).

**Verdict: fail** (item V4, visual check). V1-V3 pass.

| Item | Result | Observation |
| --- | --- | --- |
| V1 red at base | pass | New `tests/cli/hub/test_config.py` against `git archive d8ad650 src`: **3 failed, 6 passed** (the two new tests and the updated group test fail). |
| V1 green | pass | `test_config.py` + `test_no_background.py` on the branch: **16 passed**. |
| V1 gap map | pass | C-1, C-2, C-5 each map to a fix and a test; tests assert structure (Horizontal siblings, x order, borders, bold `#5fd7ff` `▶`, no bgcolor). |
| V1 group list (req. 4) | pass | `Config` has no live group (`lib/config/models.py:172`: hotkey audio asr feedback refine analytics delivery). Hub lists the actual groups, keeps `delivery`. |
| V3 gate: `ruff check .` | pass | `All checks passed!` |
| V3 gate: `ruff format --check .` | pass | `690 files already formatted` |
| V3 gate: `pytest -m "not integration"` | pass | `2664 passed, 2 skipped, 6 deselected` |
| V3 gate: `stenographer --help` | pass | exit 0 |
| Beam note figures | pass | 10.12% / 1.664 s (beam 1) and 9.31% / 1.683 s (beam 5) match the large-v3-turbo-ct2, hotwords off, context off rows of `docs/transcription-experiments.md` §"CPU model and context screen"; that model is the config default. |
| No painted background | pass | `test_hub_sections_dialogs_and_live_app_do_not_paint_backgrounds` passes; selected group has no bgcolor. |
| V4 visual check | **fail** | See below. |

## V4 — independent re-capture

Re-rendered in a pilot with fake services, default config, 150x45, ASR group:
`verifier-config.png` (this folder). Board:
`/home/penguin/source/hive/.hive/tmp/coordinator/designs/stenographer-png/Config.png`
and `.../designs/stenographer/Config.dc.html`.

| Board element | Judgement |
| --- | --- |
| C-1 file card | Matches in content: `file` / `config.toml` / numeric count. Board shows count in warn colour; colour is not set by the board rule, so not a fail. |
| C-2 group selector | Matches: bordered `group` panel left of settings, `▶ asr` bold accent, no fill. `live` absent and `delivery` kept, as req. 4 directs. |
| Settings panel title | **Differs.** The new per-group title `asr` renders in the dim border colour (`#main-content` has no `border-title-color`) and is barely legible in the capture, while the board label `┤ asr · profiles ├` is readable and the sibling `group` title uses `ansi_default`. Task 108 fixed the same defect on Live. `asr` vs `asr · profiles` is fine under decision 15. |
| C-5 hotwords | **Partly differs.** Separate area below a divider: matches. The board's value area shows the word list and a word count (`… 45 words`); the hub shows `key = value / Default / help` with no count. `visual-check.md` records C-5 as "Matches" without noting this. |
| C-5 beam note | Matches: one note at the panel bottom, citing the bench section with figures. |
| C-3 settings table | Differs, out of scope per the brief. Board: compact name/value table, one row per key, one help line for the selected key. Hub: three lines per key (`key = value`, `Default:`, help), and raw values (`cpu_threads = 0`, board `auto`). The brief keeps C-3 as is; decision 15 overrides only the second profile column, so `visual-check.md`'s "Overridden by decision 15" overstates the override. Flagged for the manager to decide scope; not a fail reason by itself. |
| C-4 context | Absent, as the brief directs. |
| C-6 key hints | All five board actions present plus nav hints; pre-existing, unchanged. |
| C-7 canvas | Overridden by task 107; no paint. |

## Fail reason

V4: (1) the new settings-panel title `asr` renders in the dim border colour and
is not legible (board label readable; fix like task 108, e.g.
`border-title-color: ansi_default` on `#main-content`); (2) the hotwords value
area lacks the board's word count, and `visual-check.md` records C-5 as
matching. Note for the manager: the settings panel remains a three-line-per-key
dump vs the board's name/value table; the brief kept C-3, so this is a scope
question, not a fail reason.
