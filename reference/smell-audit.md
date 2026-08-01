# Code-Smell Audit — 2026-08-01

Whole-repo audit of `src/stenographer/` + `tests/` against [code-smells.md](code-smells.md),
run by the `code-smell-audit` workflow (`.claude/workflows/code-smell-audit.js`).
All agents: Claude Opus 4.8. Run `wf_b73512b1-cf5`.

**Stats:** 59 files in scope · 5 category finders · 21 candidates · 21 verifier agents ·
18 kept (11 CONFIRMED, 4 PLAUSIBLE reported after merging, 3 folded as duplicates) · 3 refuted.

> Every finding was independently verified against the entry's **Signs** and **Ignore when**
> clauses by a fresh agent that read both the reference entry and the cited code.
> CONFIRMED = signs demonstrably present, code quoted. PLAUSIBLE = pattern present,
> severity a judgment call.

## Audit summary

The dominant, most-costly issue is the production-dead thread-based `Worker` path: two
ASR-worker classes with silently drifted, non-substitutable interfaces (`Worker` vs
`ProcessWorker`), where `Worker` and its `LazyModel` idle-unload machinery are constructed
only in tests yet keep a green suite while contributing nothing to the daemon. The remaining
findings are lower-cost structural taxes (scattered systemctl unit literals, two data clumps,
four oversized methods) and local cleanups (duplicate subprocess handling, dead
clipboard/feedback code).

## Resolution (2026-08-01)

Refactored by phased subagent teams (1 implementer + 2 adversarial reviewers per team,
all Opus 4.8, `.claude/workflows/refactor-team.js`), baselined at checkpoint `f84617f`:

- **Phase 1 (`07ce20d`)**: #1 (Worker/LazyModel deleted, hints retyped, 6 cancellation
  tests ported to ProcessWorker), #2 + #12 partial (`systemd.py` owns unit name/argv/
  rendering; cmd_* bodies partly remain in cli.py because out-of-boundary tests patch
  `cli.*` attributes), #3 (`_Section` parameter object), #9, #10, #11.
- **Phase 2 (`a63bd8e`)**: #4 (`Preview` dataclass; IPC wire format unchanged),
  #15 (`_compute_preview` helper), #8 (`_abort_active_job` / `_dispatch_response`).
- **Phase 3 (`0444744`)**: #5 (`Session.stop` decomposed), #6/#7 (overlay methods
  split, centralized degrade-and-cleanup), #14 (`_HUD_STATE_LABELS` single source of
  truth; missing `update_available` entry added with unchanged rendering).
- **#13**: deliberately skipped (verifier: cost of the intentional explicit-validation style).

Every phase gated on the full unit suite (537 passed) + ruff before commit. Not yet
validated: `STENOGRAPHER_INTEGRATION=1` suite and a real dictation session.

## Top findings (ranked by cost)

| # | Verdict | Location | Smell |
|---|---------|----------|-------|
| 1 | CONFIRMED | `src/stenographer/asr/worker.py:426` | [Alternative Classes with Different Interfaces](code-smells.md#alternative-classes-with-different-interfaces) — Worker vs ProcessWorker drift (absorbs the dead `Worker`/`LazyModel` findings) |
| 2 | CONFIRMED | `src/stenographer/cli.py:381` | [Shotgun Surgery](code-smells.md#shotgun-surgery) — 9 hand-built systemctl literals across 2 files |
| 3 | CONFIRMED | `src/stenographer/config.py:665` | [Data Clumps](code-smells.md#data-clumps) — `(table, key, dotted, path)` ×56 |
| 4 | CONFIRMED | `src/stenographer/live.py:446` | [Data Clumps](code-smells.md#data-clumps) — `(stable, provisional)` pair across 3 modules |
| 5 | CONFIRMED | `src/stenographer/session.py:232` | [Long Method](code-smells.md#long-method) — `Session.stop`, ~88 lines |
| 6 | CONFIRMED | `src/stenographer/visualizer.py:784` | [Long Method](code-smells.md#long-method) — `OverlayApplication._activate`, ~90 lines |
| 7 | CONFIRMED | `src/stenographer/visualizer.py:447` | [Long Method](code-smells.md#long-method) — `LayerShellOverlay._start_helper`, ~78 lines |
| 8 | CONFIRMED | `src/stenographer/asr/worker.py:659` | [Long Method](code-smells.md#long-method) — `ProcessWorker._run_process_job`, ~78 lines |
| 9 | CONFIRMED | `src/stenographer/output/inject.py:95` | [Duplicate Code](code-smells.md#duplicate-code) — twin wtype failure handlers |
| 10 | CONFIRMED | `src/stenographer/output/clipboard.py:75` | [Dead Code](code-smells.md#dead-code) — `ClipboardManager.read()` has no production caller |
| 11 | CONFIRMED | `src/stenographer/audio/feedback.py:59` | [Duplicate Code](code-smells.md#duplicate-code) — double "no asset found" warning |
| 12 | PLAUSIBLE | `src/stenographer/cli.py:355` | [Divergent Change](code-smells.md#divergent-change) — systemd logic embedded in the dispatcher |
| 13 | PLAUSIBLE | `src/stenographer/config.py:157` | [Shotgun Surgery](code-smells.md#shotgun-surgery) — 4 lockstep sites per config field |
| 14 | PLAUSIBLE | `src/stenographer/visualizer.py:924` | [Shotgun Surgery](code-smells.md#shotgun-surgery) — HUD state defined in 3 places |
| 15 | PLAUSIBLE | `src/stenographer/live.py:426` | [Feature Envy](code-smells.md#feature-envy) — `_publish_preview` scripts over transcriber word lists |

---

## Object-Orientation Abusers

### 1. Worker vs ProcessWorker — [Alternative Classes with Different Interfaces](code-smells.md#alternative-classes-with-different-interfaces) — CONFIRMED

`src/stenographer/asr/worker.py:426` · same root cause also at `worker.py:65`, `asr/model.py:294`, `worker.py:245`

Two ASR-worker classes do the same job under divergent, non-substitutable interfaces.
`Worker` (thread-based, worker.py:65) and `ProcessWorker` (process-based, worker.py:426)
have silently drifted: `ProcessWorker.submit_words` accepts `deadline=`/`priority=`
(worker.py:508) which `Worker.submit_words` (worker.py:104) does not, and `ProcessWorker`
adds `supersede_interim()` with no `Worker` equivalent.

**Cost:** `session.py:77` and `live.py:111` type-hint their worker param as `Worker`, but
`cli.py:188` always constructs a `ProcessWorker` — `Worker` is instantiated only in tests.
`live.py:155` papers over the gap with `getattr(self._worker, "supersede_interim", None)`,
and `live.py:356` passes kwargs a real `Worker` would reject with `TypeError`. Any contract
change must be mirrored across both classes plus the shims, and the type hints actively lie.
The merged findings add: the thread-based `Worker` (and the `LazyModel` idle-unload
machinery it drags along) is production-dead code kept alive only by tests, and the
`kind == "words"` dispatch is duplicated between `Worker._run` (worker.py:245) and
`_inference_process_main` (worker.py:406).

**Fix gist:** align the two interfaces — rename methods, add or parameterize arguments
until the signatures match, move any missing behaviour across — then extract a shared
superclass and delete the redundant class. Given `Worker` has no production caller, the
simpler move is likely [Dead Code](code-smells.md#dead-code)'s: delete it (version control
remembers), retype the hints to `ProcessWorker` (or a small protocol), and drop the
`getattr` shims.

## Change Preventers

### 2. systemctl invocations rebuilt at 9 sites — [Shotgun Surgery](code-smells.md#shotgun-surgery) — CONFIRMED

`src/stenographer/cli.py:381` · also cli.py:411/470/484/488, update.py:383/391/411/422, status.py:19

The unit-name literal `"stenographer.service"` is hand-rebuilt inside
`["systemctl", "--user", ...]` lists at 9 sites across `cli.py` and `update.py`, while
`status.py:19` already defines `_UNIT_NAME` — used at status.py:106/131 but not shared.

**Cost:** renaming the unit, changing manager scope, or adding a flag means nine-plus
scattered edits in three files for one conceptual change; it's easy to update the constant
and miss the literals.

**Fix gist:** pull the scattered behaviour together — one shared helper (e.g.
`_systemctl(verb, *flags)`) plus the exported unit-name constant.

### 12. cli.py mixes dispatcher with systemd management — [Divergent Change](code-smells.md#divergent-change) — PLAUSIBLE

`src/stenographer/cli.py:355`

`cmd_enable`/`cmd_start`/`cmd_stop`/`cmd_disable` (lines 355–497) plus `_render_unit` and
`_resolve_daemon_exec` embed ~140 lines of unit-file rendering and systemctl orchestration
directly in the entry-point module, with no dedicated systemd module. The verifier noted
`cmd_update` and `cmd_bench` genuinely delegate (per CLAUDE.md's documented design), so only
the systemd strand tips toward the smell — severity is a judgment call.

**Fix gist:** split out the distinct reason-to-change — a `systemd.py` module `cli.py` only
dispatches to (which would also absorb finding #2).

### 13. Config fields restated in 4 lockstep sites — [Shotgun Surgery](code-smells.md#shotgun-surgery) — PLAUSIBLE

`src/stenographer/config.py:157`

Each config field appears in the frozen dataclass, `defaults()`, the `_build_X` validator,
and `_format_default_toml` — e.g. `max_chars` at lines 108, 202, 555–561, 798. The verifier
downgraded severity: all sites are in one file, and the dataclass↔defaults pair fails loudly
(no field defaults → `TypeError`), so only `_build_X`/`_format_default_toml` are unguarded.

**Fix gist:** if it starts to bite, gather the per-field knowledge in one place (e.g. field
metadata driving defaults, parsing, and TOML rendering) — but this is a known cost of the
explicit-validation style the module deliberately uses.

### 14. HUD status states defined in 3 places — [Shotgun Surgery](code-smells.md#shotgun-surgery) — PLAUSIBLE

`src/stenographer/visualizer.py:924`

A status state is a bare slug threaded across a subprocess IPC boundary and defined in three
uncoordinated spots: `StatusIndicator.show_*` (visualizer.py:565–617), the
`DesktopNotification.show_*` fallbacks (notification.py:59–79), and the overlay's private
`labels` dict (visualizer.py:926) — which is already missing `update_available`, silently
rendering the title-cased slug instead. Mitigating: only two files, the indicator/notifier
pair is the intentional fallback contract, and the fallback degrades gracefully.

**Fix gist:** one source of truth for the state set (an enum or a single slug→label mapping
shared by both ends of the IPC).

## Bloaters

### 3. `(table, key, dotted, path)` validator clump — [Data Clumps](code-smells.md#data-clumps) — CONFIRMED

`src/stenographer/config.py:665`

All 7 `_expect_*` validators declare the identical four-parameter group, re-threaded at ~49
call sites (56 occurrences total), with the dotted path manually duplicated alongside its
key each time (`_expect_str(table, "repo", "update.repo", path)`).

**Cost:** changing the validation-error contract (line/column context, a section object)
means touching seven signatures and rippling across fifty-plus call sites.

**Fix gist:** promote the recurring group to its own object — e.g. a small `Section`
carrying `(table, dotted_prefix, path)` whose methods take just the key.

### 4. `(stable, provisional)` preview pair — [Data Clumps](code-smells.md#data-clumps) — CONFIRMED

`src/stenographer/live.py:446`

The preview pair travels as two loose strings through ~6 signatures in 3 modules:
`IncrementalDriver._on_preview` → `Session._publish_preview` (and its lambda) →
`StatusIndicator.show_preview` → `LayerShellOverlay.show_preview` → `_preview_markup`.
The provisional tail is meaningless without the committed prefix — one domain concept.

**Cost:** adding a third preview field (e.g. a confidence marker) requires editing all the
parallel signatures in lockstep.

**Fix gist:** a small frozen `Preview` dataclass passed through the chain.

### 5. `Session.stop` — [Long Method](code-smells.md#long-method) — CONFIRMED

`src/stenographer/session.py:232` (~88 lines)

Mixes recorder/streamer handling, listener stop, forced-shutdown escalation,
timeout-budget arithmetic, and four near-identical per-component `try/except` close blocks
at mixed abstraction levels.

**Fix gist:** extract each coherent block into its own well-named method (e.g.
`_stop_capture`, `_drain_processor(deadline)`, `_close_components`).

### 6. `OverlayApplication._activate` — [Long Method](code-smells.md#long-method) — CONFIRMED

`src/stenographer/visualizer.py:784` (~90 lines)

Font/CSS setup, layer-shell surface protocol config, full manual GTK widget-tree
construction, input-region setup, and the READY handshake in one method, error-exits
interleaved throughout; no seam to test widget construction apart from surface init.

**Fix gist:** extract `_install_styles()`, `_configure_layer_shell()`, `_build_widgets()`.

### 7. `LayerShellOverlay._start_helper` — [Long Method](code-smells.md#long-method) — CONFIRMED

`src/stenographer/visualizer.py:447` (~78 lines)

Five concerns inline — availability guards, command build, LD_PRELOAD library resolution,
subprocess spawn, select()-based READY handshake, configure write — with the
`self._degrade(); return False` pattern repeated in four branches, where a missed branch
leaks a live subprocess.

**Fix gist:** extract the stages; centralize the degrade-and-cleanup exit path.

### 8. `ProcessWorker._run_process_job` — [Long Method](code-smells.md#long-method) — CONFIRMED

`src/stenographer/asr/worker.py:659` (~78 lines)

A poll loop re-checking force-stop / cancellation / deadline / child liveness each
iteration, followed by a five-way response-name dispatch, with guard checks and message
decoding at two abstraction levels.

**Fix gist:** extract the guard evaluation and the message dispatch
([Decompose Conditional](refactoring-techniques.md#decompose-conditional) /
[Extract Method](refactoring-techniques.md#extract-method)).

## Dispensables

### 9. Twin wtype failure handlers — [Duplicate Code](code-smells.md#duplicate-code) — CONFIRMED

`src/stenographer/output/inject.py:95` (with lines 55–72)

`type_text` and `paste` repeat the same except-block verbatim: same three-exception tuple,
same rc-extraction ternary, same stderr-decode ternary — and the log messages have already
drifted.

**Fix gist:** extract a shared `_run_wtype(argv, log_context)` (or a failure-classifying
helper) both methods call.

### 10. `ClipboardManager.read()` — [Dead Code](code-smells.md#dead-code) — CONFIRMED

`src/stenographer/output/clipboard.py:75`

Docstring says "Used by tests"; the class docstring and CLAUDE.md confirm the daemon never
reads the clipboard. Only `tests/test_clipboard.py` calls it — and the integration test
already verifies `copy()` via its own `_read_selection` helper.

**Fix gist:** delete it (version control remembers); point the remaining unit tests at the
test helper.

### 11. Double "no asset found" warning — [Duplicate Code](code-smells.md#duplicate-code) — CONFIRMED

`src/stenographer/audio/feedback.py:59`

`_resolve_path` logs `"cue %r: no asset found; skipping"` at line 51 and returns `None`;
`play()` logs the byte-identical message again at line 59 on that `None`. One missing cue →
two identical log lines.

**Fix gist:** drop one of the two warnings (log ownership belongs in `_resolve_path`).

## Couplers

### 15. `_publish_preview` scripts over transcriber data — [Feature Envy](code-smells.md#feature-envy) — PLAUSIBLE

`src/stenographer/live.py:426`

The method pulls `committed_words` + `provisional_words` and rebuilds two throwaway
`HeuristicFormatter`s to reconstruct the stable/provisional split via
`complete[len(stable):]` string slicing — fragile to any `format_batch` change. The
verifier kept it PLAUSIBLE: the obvious Move Method target is blocked, because
`StreamingTranscriber` is a documented **pure** committer and formatting is deliberately
not its concern — so this reads partly as driver-side orchestration, not pure envy.

**Fix gist:** if it bites, extract the preview-split computation into its own helper owned
by the driver (keeping the pure-module boundary), rather than moving it onto the
transcriber.

---

## Refuted candidates

<details>
<summary>3 candidates refuted by verifiers (with evidence)</summary>

- `src/stenographer/visualizer.py:565` — *alternative-classes-with-different-interfaces*:
  `DesktopNotification` vs `LayerShellOverlay` interfaces. Refuted — the classes are
  complementary (overlay adds `show_levels`/`show_preview`), not interchangeable duplicates;
  the fallback mapping is the documented degrade contract.
- `src/stenographer/session.py:349` — *inappropriate-intimacy*: the
  `streamer.abort.set(); streamer.signal_abort()` two-step. Refuted — both are the driver's
  public, documented API, not reached-into internals.
- `src/stenographer/visualizer.py:271` — *inappropriate-intimacy*: untyped JSON IPC between
  `LayerShellOverlay` and `OverlayApplication._handle_command`. Refuted — a string-keyed
  IPC protocol between a parent and its own helper subprocess is a deliberate process
  boundary, not eroded encapsulation between classes.

</details>

---

*Re-run any time: `Workflow({name: "code-smell-audit"})`, optionally with a narrowing
target (e.g. `"only src/stenographer/live.py"`). Fix mechanics for every smell are in
[refactoring-techniques.md](refactoring-techniques.md) via each entry's **Treatments** links.*
