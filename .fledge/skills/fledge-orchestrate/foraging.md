# Foraging protocol

Agent-neutral context-gathering protocol used by the planning phase when the `spawn-worker` primitive is available. Two roles: a **forager** (one, commissioned by whoever runs the planning phase — the incubator when planning is delegated, else the orchestrator; see `planning.md` §0/§2) that orchestrates **scouts** (many, spawned by the forager) and synthesizes their reports. Foraging runs in the planner's own session only when `spawn-worker` is unavailable (in which case the planner performs both roles per `planning.md` step 2).

A spawn prompt is a worker's entire context — it inherits no conversation history — and must be fully self-contained.

## Commissioner

You are the commissioner when you spawn a forager and wait on it: the orchestrator on a standalone context-regeneration request or when planning runs inline, or the incubator when planning is delegated. This section is the single source of truth for how to wait — `planning.md` §2 and `worker-protocols.md` point here. Your entire job while the forager runs is to **wait correctly and cheaply**. The forager does the work; you must not shadow it.

**Obtain the forager.** Spawn a `fledge-forager` worker (named per the species scheme in `implementation.md` §3.1), or — if you cannot spawn workers yourself — request one via the channel your protocol defines, naming yourself as the party it reports to. Foragers are one-shot: obtain a fresh one for each regeneration. If you provide no `spawn-worker` at all, you have no forager to wait on — run the forager pipeline below yourself, sequentially, instead of reading this section.

**Wait as a two-input state machine.** Once the forager is running, exactly one signal means it is done: **its explicit by-name final message** (the coverage summary it sends you). Everything else is noise for this decision:

- **You are re-invoked by events, so you never poll.** Your harness wakes you when the forager sends a message or its lifecycle changes. Do **not** run `sleep`, timed wait-loops, or repeated status checks to "wait." Do **not** `wc`, `cat`, `ls`, or otherwise eyeball `.fledge/nest/` to judge progress — a half-written nest is the *expected* mid-run state (scaffolded stubs, raw reports filling in, concern docs synthesizing) and tells you nothing about whether the forager is done or stuck. Eyeballing that state is exactly what produces false stalls and wasteful churn.
- **Idle is neither done nor stalled.** A "teammate finished/idle" or "worker finished" lifecycle notification is **not** the final message — a persistent worker goes idle whenever its turn ends, including harmlessly between its own pipeline steps. Receiving one is not permission to conclude anything.

**Disambiguate a suspected stall with the CLI, not your eyes.** If — and only if — you get a genuine idle with no final message and want to know whether the forager actually still owes work, run `fledge nest status` **once**. It is the authoritative done-check (all concern docs synthesized, index stamped to HEAD): exit 0 / `complete: true` means the nest is finished, exit non-zero names exactly what is still missing or a stub.

- `complete: true`, but no final message yet → the forager finished the work but hasn't announced. Send it one by-name message asking it to send its final coverage summary; do not churn or respawn it.
- `complete: false` → it genuinely still owes synthesis. Send it **one** by-name message asking it to continue and report when done, then go back to waiting for the next event. Repeat at most a few times across successive idles — never in a tight loop, never with `sleep`. This CLI verdict is the *only* sanctioned reading of on-disk state, and it only ever decides nudge-vs-wait; it never declares the forager done. Only its final message does that.

If repeated by-name nudges across successive idles still produce no final message, do not decide unilaterally: surface the situation to the user through a `confirm-gate` (intervene — terminate and respawn a fresh forager, or fall back to inline synthesis — or keep waiting). Only the user chooses to abandon a forager.

**On the final message, verify and release.** When the by-name final message arrives, confirm the result with `fledge nest status` (it should report complete, with `index.md`'s `commit` at HEAD), relay the forager's coverage notes, and request the forager's graceful shutdown by name; the party holding the `spawn-worker`/kill primitive (on Claude Code, the orchestrator, `team-lead`) force-terminates it if it does not exit promptly — acknowledging a shutdown request is not the same as ending its session. Its species frees only once shutdown is confirmed.

## Forager

You produce the `.fledge/nest/` document set that downstream planning agents rely on. You orchestrate cheap scouts to do the reading; you do the synthesis. You never modify source code — your writes are confined to `.fledge/nest/`.

### Pipeline

1. **Scan.** Run `fledge scan` from the repo root. It emits modules (top-level directories plus `root`) with file lists, counts, and byte sizes, already filtered by `.fledgeignore`. Treat its output as the authoritative work list — do not add files it excluded.
2. **Plan the scout split.** One scout per module as the baseline, adjusted by context size:
   - Merge small modules (roughly < 5 files and < 20 KB combined) into a single scout assignment named after the largest member (note merged members in the prompt).
   - Split large modules (roughly > 100 files or > 300 KB) into multiple scouts by subdirectory, named `<module>-<subdir>`.
3. **Full regeneration.** Run `fledge nest scaffold` from the repo root. This clears `.fledge/nest/` (including `raw/`) and recreates the directories. Every run rebuilds from scratch; never merge with stale docs. **Important:** immediately after `fledge nest scaffold`, `.fledge/nest/` contains only empty template stubs — placeholder concern docs, unfilled `raw/*.md`, and `index.md` frontmatter stamped to HEAD. This empty state is the expected intermediate after scaffolding; scouts and synthesis fill it in steps 4–6 below. It is not a failure and must not be flagged as one.
4. **Fan out scouts.** Spawn one `fledge-context-scout` worker per assignment, all in parallel. Each spawn prompt must contain: the module name, the exact file list, and the instruction to run `fledge nest scout --module <module>` to create the report file, then fill every section body. Scouts return one-line confirmations; verify each expected raw report file exists afterward, and re-spawn any scout whose report is missing (once).

   Fanning out scouts in parallel yields your turn until they return, and their completion is **not** your own completion — you still owe steps 5 and 6. On every wake, re-anchor to your position in this pipeline from what is on disk before doing anything else: if the raw reports exist but the eight concern docs are still empty template stubs, you are between step 4 and step 5 — proceed straight into synthesis. Do not go idle, and do not send a final message, until step 6 is written. The scouts finishing is your cue to synthesize, never a reason to stop.
5. **Synthesize concern documents.** Read the raw reports and write these eight documents to `.fledge/nest/`, following the conventions in `templates/context-doc.md`:

   | Document | Synthesized from (report sections) |
   |---|---|
   | `architecture.md` | Purpose + Structure & Key Files, cross-module relationships |
   | `modules.md` | Repo map: each module → purpose → key files → "look here for…" |
   | `conventions.md` | Conventions Observed, reconciled across modules |
   | `data-model.md` | Data Types |
   | `dependencies.md` | External Dependencies, deduplicated with usage notes |
   | `entry-points.md` | Entry Points & Public Interfaces; how to run/build the project |
   | `testing.md` | Tests: frameworks, how to run, coverage patterns |
   | `domain.md` | Domain Terms: glossary of business/domain concepts |

   Synthesize — do not concatenate. Resolve contradictions between reports by re-reading the source file in question. Carry forward unresolved scout Open Questions into the relevant doc under an `## Open Questions` section.
6. **Write the index.** Write `.fledge/nest/index.md` last. Header records generated datetime and `git rev-parse HEAD`. One entry per concern doc: filename, 2–3 sentence summary of what it actually contains (not a generic description), and a `Read this when:` line. This index is what downstream agents read first to decide which docs to load — write the summaries for that decision.
7. **Verify before you report.** Run `fledge nest status`. It must report complete (exit 0 / `complete: true`): every concern doc synthesized past its template stub, and `index.md` stamped to HEAD. If it reports anything incomplete, you are **not** done — it names exactly which docs are still stubs or missing; finish those (and re-stamp the index if HEAD moved), then re-run it until it is clean. Only then send your final message. This check is what distinguishes "my scouts finished" from "the nest is done" — passing it is the gate on reporting.

### Frontmatter

Frontmatter is written by the CLI: `fledge nest scaffold` stamps every file it creates; refresh any file's frontmatter with `fledge nest stamp <file>`.

### Final message

Report: modules scanned, scouts spawned (and any re-spawns), documents written, and anything that materially limited coverage (unreadable files, empty modules, scan failures). Keep it under ten lines.

### Lifecycle

A forager is one-shot, but "one-shot" ends when `fledge nest status` reports complete (step 7), not at the scout fan-out. You are done only once every pipeline step is written, `fledge nest status` passes, **and** you have sent your final message. Going idle before that final message is a stall, not completion: if you find yourself idle with the raw reports present and the concern docs still stubs, you have stopped mid-pipeline — resume synthesis immediately rather than waiting to be prompted. `fledge nest status` is your objective check for exactly this: run it on any wake to see whether you still owe synthesis. After the final message you have no further work. In harnesses where workers persist after their final message, the party that commissioned it requests its shutdown by name once the nest output is verified — comply promptly, and expect the orchestrator (on Claude Code, `team-lead`; the party holding the `spawn-worker`/kill primitive) to force-terminate you if you do not exit promptly, since acknowledging a shutdown request is not the same as ending your session. Scouts are unnamed (no species): they self-terminate on their one-line final message and are never addressed by name.

## Scout

A scout's prompt assigns a module name and an explicit list of files. Its entire job is to examine those files and write exactly one report file. It never modifies source code, and never writes any file other than its assigned report.

### Rules

- Read ONLY the files assigned in the prompt. Do not wander into other modules.
- Use `read-only-shell` only for read-only inspection (`wc`, `file`, `head`, `git log --oneline -- <path>`), never to mutate anything.
- Run `fledge nest scout --module <module>` to create `.fledge/nest/raw/<module>.md` with the correct structure and frontmatter. Then fill every section body in that file.
- Follow the section order in `templates/scout-report.md` in this skill's directory exactly — every section present, in order. Write `None observed.` under any section with nothing to report; never omit a section.
- Frontmatter is stamped by `fledge nest scout`; refresh it with `fledge nest stamp <file>` if needed.
- Report facts you observed, with file paths. Do not speculate about code you did not read; put uncertainties under Open Questions.
- Any count, total, or enumerated size you state (e.g. "N commands," "N fixtures," "N files in module X") must come from an exact computation run at write time — a `grep -c`, a `find`/glob count, `wc -l`, or equivalent — never estimated by eye or recalled from memory. Cite or show the command that produced it so the count is re-derivable by a later reader, not merely asserted. This applies equally to counts carried into any synthesized doc.
- Be dense: bullet points, file references, identifier names. No prose padding.

### Final message

A scout's final message must be a single line:

`report written: .fledge/nest/raw/<module>.md, N files examined`
