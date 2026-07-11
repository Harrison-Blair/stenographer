# Foraging protocol

Agent-neutral context-gathering protocol used by the planning phase when the `spawn-worker` primitive is available. Two roles: a **forager** (one, commissioned by whoever runs the planning phase — the incubator when planning is delegated, else the orchestrator; see `planning.md` §0/§2) that orchestrates **scouts** (many, spawned by the forager) and synthesizes their reports. Foraging runs in the planner's own session only when `spawn-worker` is unavailable (in which case the planner performs both roles per `planning.md` step 2).

A spawn prompt is a worker's entire context — it inherits no conversation history — and must be fully self-contained.

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

### Frontmatter

Frontmatter is written by the CLI: `fledge nest scaffold` stamps every file it creates; refresh any file's frontmatter with `fledge nest stamp <file>`.

### Final message

Report: modules scanned, scouts spawned (and any re-spawns), documents written, and anything that materially limited coverage (unreadable files, empty modules, scan failures). Keep it under ten lines.

### Lifecycle

A forager is one-shot, but "one-shot" ends at step 6, not at the scout fan-out. You are done only once all six pipeline steps are written **and** you have sent your final message. Going idle before that final message is a stall, not completion: if you find yourself idle with the raw reports present and the concern docs still stubs, you have stopped mid-pipeline — resume synthesis immediately rather than waiting to be prompted. After the final message you have no further work. In harnesses where workers persist after their final message, the worker that commissioned it (the incubator or the orchestrator) will request its shutdown by name once the nest output is verified — comply promptly. Scouts are unnamed (no species): they self-terminate on their one-line final message and are never addressed by name.

## Scout

A scout's prompt assigns a module name and an explicit list of files. Its entire job is to examine those files and write exactly one report file. It never modifies source code, and never writes any file other than its assigned report.

### Rules

- Read ONLY the files assigned in the prompt. Do not wander into other modules.
- Use `read-only-shell` only for read-only inspection (`wc`, `file`, `head`, `git log --oneline -- <path>`), never to mutate anything.
- Run `fledge nest scout --module <module>` to create `.fledge/nest/raw/<module>.md` with the correct structure and frontmatter. Then fill every section body in that file.
- Follow the section order in `templates/scout-report.md` in this skill's directory exactly — every section present, in order. Write `None observed.` under any section with nothing to report; never omit a section.
- Frontmatter is stamped by `fledge nest scout`; refresh it with `fledge nest stamp <file>` if needed.
- Report facts you observed, with file paths. Do not speculate about code you did not read; put uncertainties under Open Questions.
- Be dense: bullet points, file references, identifier names. No prose padding.

### Final message

A scout's final message must be a single line:

`report written: .fledge/nest/raw/<module>.md, N files examined`
