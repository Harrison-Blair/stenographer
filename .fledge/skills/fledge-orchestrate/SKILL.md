---
name: fledge-orchestrate
description: Orchestrates fledge spec-driven development workflows in a fledge-managed repository (one containing a .fledge/ directory). Use when the user asks to make a plan, plan a feature, write plumages, or author feathers. Routes to the appropriate phase.
---

# fledge-orchestrate

You are running the fledge orchestration workflow. Fledge is a spec-driven development tool: repository knowledge lives in `.fledge/nest/`, feature intent lives in `.fledge/pluma/plumage/` (the plumages, i.e. requirements), and implementable work lives in `.fledge/pluma/feathers/` (the feathers, i.e. tasks).

## Routing

Determine which phase the user's request calls for and load that phase's instructions from this skill's directory:

| Request looks like | Phase | Instructions |
|---|---|---|
| "make a plan", "plan <feature>", "write plumages for…", "break this into feathers", "author feathers for PLM-###" | Planning | Read `planning.md` in this skill's directory and follow it |
| "implement", "implement PLM-###", "implement FTHR-###", "start implementation", "run the feathers" | Implementation | Read `implementation.md` in this skill's directory and follow it |
| Anything else (review, …) | Not built yet | Say so plainly; offer an existing phase if it fits |

Future phases will be added as sibling files to `planning.md`.

## Primitives and your adapter

Fledge's workflow is **agent-neutral**: it is written to a fixed set of orchestration *primitives* (the 6-primitive contract in `implementation.md`), not to any one agent harness. Your harness provides each primitive through a harness-specific mechanism.

Before driving a phase, locate your **adapter documentation** — the files your harness auto-loads (subagent definitions, prompt templates, or a root `AGENTS.md`) point to it. There you will find:

- the **primitive map** — how each fledge primitive is realized in your harness (`confirm-gate`, `read-only-shell`, `write-file`, `run-fledge`, `spawn-worker`, `message-peer`); and
- the **piping notes** — harness runtime behavior (teammate display, recovery after resume, permission inheritance) where applicable.

Phases below refer to primitives by name ("run a `confirm-gate`", "spawn a `spawn-worker`"); your adapter's map tells you how. Capability-conditional prose in a phase ("if you provide `spawn-worker`…") branches on which primitives your adapter declares.

## Ground rules (all phases)

- Verify this is a fledge-managed repo (a `.fledge/` directory exists at the git root). If not, stop and ask whether to initialize one (`fledge init` creates the scaffold).
- Deterministic spec operations go through the `fledge` CLI — never hand-edit what it can write. Creation: `fledge new plumage|feather` (ID allocation, filenames, frontmatter). Status: `fledge status <ID> <new>`. Other frontmatter fields: `fledge set`. Readiness/structure: `fledge ready`, `fledge vee`, and `fledge unfledged` to survey all non-fledged plumage and feathers (`--plumage`/`--feathers` to scope, `--json` for a machine-readable contract). Validation: `fledge preen`. Feather claims: `fledge brood`/`abandon`/`broods`. Spec *bodies* (prose sections) are yours to write and edit directly.
- Run `fledge preen` as a pre-flight before closing any phase; fix errors before proceeding.
- All generated files carry frontmatter with authored/generated datetime (UTC ISO 8601), authoring agent, and `fledge_version` — `fledge new` stamps these automatically.
- Decisions belong to the user; facts belong in the repo. Look up facts, interrogate for decisions.
- **Confirmation gates (`confirm-gate` primitive).** Two modes. A *review* gate presents the full material under review (file contents, diff, outline, or list — never a summary that hides what is being approved), then asks for a structured choice: exactly "Accept" and "Make changes". On "Make changes", gather feedback, revise, re-present the revised material in full, and ask again — loop until "Accept". A *decision* gate presents a choice between concrete options as the question's choices. Refusal (choosing "Make changes" indefinitely, or declining a decision gate) **pauses the phase cleanly**: spec state is untouched and you report `paused at <gate>, awaiting your direction`. Never treat silence, or a "looks good" buried in an answer to something else, as passage through a gate. When the planning phase is delegated (`planning.md` §0), gates originate from the incubator worker: the orchestrator presents the relayed material to the user verbatim through its `confirm-gate` mechanism and returns the choice verbatim — the gate semantics here are unchanged.
- **Author-to-draft-then-gate.** When a phase authors a spec file and then gates on it, draft the full file content (frontmatter + body) in a buffer first and run the gate *before* committing the file via the CLI. You may note the prospective next ID by listing the relevant folder (`.fledge/pluma/plumage/` or `.fledge/pluma/feathers/`). On "Accept", create the file with `fledge new …` (it allocates the real ID) and write the body. On "Make changes", no spec mutation has occurred — revise the draft and re-gate. A refusal never leaves an un-gated file on disk.
- Acceptance criteria are checkbox lists (`- [ ] AC-N: …`), authored unchecked and only ever checked via `fledge criteria check` — never hand-edit a box. `fledge abandon --fledged` and `fledge status <PLM> fledged` refuse while boxes are unchecked; `fledge preen` errors on fledged specs with unchecked boxes.
- Templates referenced by a phase live self-relatively in this skill's `templates/` directory (e.g. `templates/scout-report.md`), never in a harness-specific path.
