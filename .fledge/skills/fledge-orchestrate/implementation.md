# Implementation phase

Executes ready feathers from `.fledge/pluma/feathers/`. This phase runs in the main session — you are the **orchestrator**: you dispatch, gate, merge, and triage. How much you delegate depends on which primitives your adapter provides (see §primitives).

Your fledge role name is `fledge-orchestrator` — fledge prefix, no species postfix. On a team harness, though, teammates address you by your **harness-assigned** name, which may differ (e.g. on Claude Code the lead is `team-lead`); your adapter's piping file gives it. Use that harness name whenever you tell a worker how to reach you, and use it consistently. (In solo tiers you address the user directly; there are no teammates.)

## Primitives — the 6-primitive contract

Fledge's workflow is written to six primitives. Your adapter declares which it provides (see your adapter's primitive map). This phase branches on that declaration:

| Primitive | Capability (what the worker may attempt) | Tier required for |
|---|---|---|
| `confirm-gate` | present material, get a structured Accept/Make-changes or option choice | A |
| `read-only-shell` | run read-only shell commands | A |
| `write-file` | write a file | A |
| `run-fledge` | run any `fledge` CLI subcommand (incl. all spec mutation) | A |
| `spawn-worker` | spawn a fresh, context-free, named, addressable, killable sub-session that returns one final message | B (foraging), C (brooders and skuas) |
| `message-peer` | send an async by-name message; sender may idle, woken on reply | C (fix loop) |

**Tier derivation (never declared — it falls out of coverage):**
- **Tier A (solo):** `confirm-gate` + `read-only-shell` + `write-file` + `run-fledge` (4). You implement each feather yourself, gating with the user. Follow §solo.
- **+Tier B (fan-out foraging):** adds `spawn-worker` (5). You may fan out foraging scouts (planning) and, during implementation, may spawn short-lived worker scouts to read code — but implementation is still solo: you implement each feather yourself. Follow §solo.
- **+Tier C (team loop):** adds `message-peer` (6). You may run the brooder/skua team loop. Follow §team; fall back to §solo for any feather you choose not to team-ify.

**Instructed rules (not primitives — stated here at point of use):**
- "Never hand-edit spec frontmatter the CLI can write" — all spec mutation goes through `run-fledge`.
- Role-specific shell constraints: scouts read-only; foragers write-confined to `.fledge/nest/`; brooders work only in their worktree. These are instructed rules; real safety backstop lives in the CLI + git + locks.
- Communication topology (brooder↔skua↔orchestrator only) is an instructed rule, not the `message-peer` primitive. (The planning phase adds incubator↔orchestrator and forager→incubator channels — see `planning.md` §0 and `worker-protocols.md` §Incubator.)
- The team task list / roster is orchestrator bookkeeping, not a primitive.

## 1. Resolve scope

Map the user's request to a feather set:

- "implement PLM-###" → all of that plumage's feathers.
- "implement FTHR-###" (or a list) → exactly those feathers; verify every feather in their `depends_on` closure is either `fledged` or in the set (`fledge vee --json` gives the full dependency data), and surface any that aren't before proceeding.
- bare "implement" → the ready set is `fledge ready --json` (it recomputes readiness from `depends_on` completion — the persisted `pipping`/`egg` field is only an authoring-time hint — and excludes feathers with a held lock). Present the set and run a `confirm-gate` (review) on it; "Make changes" adjusts the set and re-presents.

Then gate:

- `fledge preen` passes with no errors. Fix findings before dispatching.
- Context freshness: apply the freshness gate from `planning.md` step 1 (`fledge nest status --json` → `index_commit_matches`; ask before regenerating).
- The working tree on main is clean and the full test suite passes (see `.fledge/nest/testing.md` for how). Do not start onto a broken baseline.
- The feather specs, plumages, and `.fledge/nest/` docs are committed — worktrees are created from main and only contain committed files. If they aren't, present the uncommitted paths and run a `confirm-gate` (decision): commit them now, or stop so the user can handle it.
- **Tier C only — harness piping preconditions:** see your adapter's piping file for teammate-display and permission-mode preconditions (e.g. running inside tmux, and a permission mode that won't prompt per-action in teammate panes). Some preconditions auto-resolve without a gate — your piping file states which ones and what each resolved path is. For any precondition your piping file says to gate instead, never silently proceed past it unmet.

## 2. Solo implementation (Tier A and B)

You implement each ready feather directly. Maintain the ready set continuously with `fledge ready`; start a feather the moment it becomes ready.

For each feather:

1. **Read.** Read the feather spec fully, then the context docs named in its Affected Modules. (If you provide `spawn-worker`, you may spawn a short-lived scout worker to gather the affected code; otherwise read it yourself.)
2. **Worktree.** Create a worktree: `git worktree add <scratchpad or .fledge/burrows>/FTHR-### -b feather/FTHR-###-<kebab>` from main. Work only in that worktree.
3. **Claim.** `fledge brood FTHR-### --owner fledge-orchestrator --branch feather/FTHR-###-<kebab>` (atomically creates the lock and sets `status: hatching`). You run `fledge` on main; never edit the dispatched feather's spec file on main after claiming — criteria boxes ride the branch.
4. **Test-first — no exceptions.** Write the tests named in the spec's Tests section. Run them against the unchanged code and **capture the output showing them FAILING for the expected reason**; record it verbatim at capture time in `.fledge/molt/FTHR-###.md` (written inside the worktree) under a `## AC-1` heading. Implement until those tests pass. Never weaken, skip, or delete a test to make it pass.
5. **Scope discipline.** Only changes that trace directly to the feather spec. No speculative features, abstractions, or configurability. Don't "improve" adjacent code; match existing style. Remove only orphans your own changes created. Commit your work in logical units; never add attribution trailers.
6. **Evidence per criterion.** Your evidence file holds one `## AC-N` section per acceptance criterion: the commands run and their verbatim captured output (for AC-1, the failing pre-implementation run; add the passing post-implementation run once it exists). Write each section as its criterion is satisfied.
7. **Review gate.** When your tests pass and the criteria are met, present the user the full diff and the AC-by-AC evidence and run a `confirm-gate` (review): Accept / Make changes.
   - `oversight: during` feathers: surface decision checkpoints to the user as you reach them (you have no separate implementer to proxy), relaying each decision and its outcome.
   - `oversight: merge` feathers: the review gate in step 7 *is* the merge sign-off; on Accept proceed to merge.
8. **On Accept.** Check each AC box with `fledge criteria check FTHR-### <n>` (run in the worktree) and commit the spec-only change to the feather branch. Verify `fledge criteria FTHR-### --json` shows every box checked. Merge the branch to main (prefer a regular merge; on conflict, rebase onto main, re-run tests, re-merge). Run the full test suite on main.
   - **Green:** verify the criteria arrived with the merge, then `fledge abandon FTHR-### --fledged` (releases the lock, sets `status: fledged`; refuses while boxes are unchecked). Commit the spec update, remove the worktree (`git worktree remove`), delete the branch.
   - **Red:** fix in the worktree, commit to the same branch, re-run tests, re-merge and re-run the suite. Loop until green.
9. **Red → fix loop.** As in the green teardown: the fix reaches main only through the merge.
10. **Next.** Re-evaluate the ready set and start newly unblocked feathers. Shrink nothing mid-run.
11. **Plumage closeout:** run `fledge colony --json` and find the just-completed feather's plumage in its `plumages` array; treat the plumage as ready to close only when that entry's `fledged` count equals its `total` (every feather fledged — `done == total`). When it is, verify each plumage acceptance criterion — citing which feathers and evidence files satisfy it — and present that AC-by-AC accounting through a `confirm-gate` (review). On "Accept", check each box with `fledge criteria check PLM-### <n>` on main, run `fledge status PLM-### fledged`, and commit the spec update. On "Make changes", the gap goes back into the run before the plumage can close.

## 3. Team loop (Tier C)

If you provide `spawn-worker` + `message-peer`, you may run the team loop: ephemeral `fledge-brooder`/`fledge-skua` **pairs** — one pair per feather, spawned together at dispatch, the brooder in its own git worktree, its dedicated skua reviewing only that feather. You do not implement or review code yourself — you dispatch, gate, merge, and triage. For the per-primitive mechanism ("spawn-worker = ?" in your harness), see your adapter's map; for harness runtime behavior (teammate display, `/resume` recovery, permission inheritance, team task list), see your adapter's piping file.

Communication topology is strict: each brooder talks only to its paired skua and to you; each skua talks only to its paired brooder and to you. There are no other peer channels — boundary questions between feathers route through you. Workers can technically address any worker by name; this topology is a rule you and they enforce, not a technical limit.

Workers inherit no conversation history — a spawn prompt is a worker's entire context and must be fully self-contained (a `spawn-worker` is fresh, named, addressable, killable, may idle, and returns one final message).

### 3.1 Dispatch loop

Maintain the ready set continuously with `fledge ready` — a feather is ready when every feather in its `depends_on` is `fledged` and no lock is held on it. Dispatch the moment a feather becomes ready — do not wait for sibling feathers ("waves" are reporting language only).

For each feather dispatched:

1. **Oversight gate (during):** if the feather's frontmatter has `oversight: during`, STOP and run a `confirm-gate` (decision) to confirm the user is ready to participate before spawning. Do not dispatch it until they confirm; keep dispatching other ready feathers meanwhile. Because the brooder may message only its skua and you, you are the user's proxy for this feather: instruct the brooder in its spawn prompt to surface decision checkpoints to you rather than deciding autonomously, and relay each one to the user and their answer back.
2. Create a worktree: `git worktree add <scratchpad or .fledge/burrows>/FTHR-### -b feather/FTHR-###-<kebab>` from main.
3. Pick the pair's species (naming scheme below) and spawn the feather's dedicated `fledge-skua-<species>` worker (`spawn-worker`, like any other worker), whose spawn prompt contains: its own name, the feather ID and spec path, the worktree path and branch, the evidence-file path (`.fledge/molt/FTHR-###.md`), its paired brooder's name (`fledge-brooder-<species>`), your harness-assigned orchestrator name, and that it reviews this one feather only and lives only until it merges.
4. Spawn the paired `fledge-brooder-<species>` worker (see your adapter's map), whose spawn prompt contains: its own name and feather ID, the feather spec path, the worktree path and branch, its evidence-file path (`.fledge/molt/FTHR-###.md`, written inside the worktree) and the duty to record per-criterion evidence there, its paired skua's name (same species), your harness-assigned orchestrator name (the name the worker must use to reach you — e.g. `team-lead` on Claude Code; see your adapter's piping file), and which `.fledge/nest/` docs to read (from the feather's Affected Modules citations).
5. Claim the feather: `fledge brood FTHR-### --owner <worker-name> --branch feather/FTHR-###-<kebab> --worktree <path>` (the same worktree path created in step 2). This atomically creates the lock (failing loudly if another dispatch already holds it) and sets the feather file's `status: hatching` in one step (you run fledge on main; brooders never touch spec files — the paired skua is the only worker that mutates one, checking AC boxes via `fledge criteria` in the worktree). From this point until the branch merges, do not edit the dispatched feather's spec file on main — the skua's checked boxes ride the branch and a mid-flight edit conflicts at merge. Track the name→feather mapping in your roster.
6. Mirror into the shared team task list (your harness's piping file describes how it is kept): create a team task titled `FTHR-###: <title>`, assigned to that brooder, state in-progress. You are the **sole writer** of the team task list — workers never create, claim, or update entries. It is a visibility mirror only; spec frontmatter is the source of truth and wins on any disagreement.

A skua idle while its brooder implements is normal — idle is not completion; it stays alive and addressable until its feather's green teardown.

**Naming scheme:** a worker's name is its role name plus a unique species identifier — `<role>-<species>`, e.g. `fledge-brooder-adelie`, `fledge-skua-emperor`. The species come from `internal/roster`'s canonical species list — the single source of truth for the set and its allocation order; don't re-enumerate it here. The name is set at spawn and is how you and other workers address it. The scheme covers every `spawn-worker` you create, including the incubator and forager spawned during planning (`fledge-incubator-<species>`, `fledge-forager-<species>`); scouts (spawned by the forager, never addressed by name) are exempt and take no species. Species identifiers are for spawned workers only — you never take a species (your fledge role is `fledge-orchestrator`; teammates reach you by your harness-assigned name — see §orchestrator identity above and your adapter's piping file). One species per **worker pair** — a feather's brooder and skua share the species (`fledge-brooder-adelie` + `fledge-skua-adelie`); solo spawns like the forager take a species of their own.

Allocate species through the roster CLI, never by tracking usage in context. For a feather's pair, run `fledge roster assign --feather FTHR-### --pair`; it reserves the first unused species and prints the two names to use (`fledge-brooder-<species>` and `fledge-skua-<species>`). For a solo spawn (e.g. a forager or incubator), run the same command without `--pair` to reserve a single species. The roster persists the current name→feather assignments, so it — not your context — is the record of what is in use; when every base species is taken the CLI automatically hands out a numeric-suffixed variant (`adelie-2`, `-3`, …), so allocation never blocks dispatch. A species is not freed until you release it (§3.2), and you release it only once every worker bearing it is **confirmed shut down** — observably gone per your adapter's piping file (absent from the roster / its session ended), not merely having acked a shutdown request; a named worker cannot end its own session, so it may ack and then linger idle. Report a one-line roster delta to the user whenever it changes (e.g. `+ fledge-brooder-gentoo, fledge-skua-gentoo → FTHR-007`); `fledge roster` lists the current name→feather assignments on request.

### 3.2 On approval

A feather is cleared for merge in one of two ways: its skua messages you a pass (having checked every AC box in the worktree and committed that change), or — after a skua's 3rd-rejection escalation (§4), presenting the unresolved findings and cycle history — the user chooses (decision gate) to ship anyway (waiving the findings) rather than send it back for another cycle. On a user override, record the accepted (waived) findings on the feather file and use `--force` on the criteria-gated commands, so the decision is auditable. Then:

1. **Oversight gate (merge):** if the feather has `oversight: merge`, hold the branch unmerged. Show the user the full diff and the skua's verdict, then run a `confirm-gate` (review): Merge / Make changes ("Make changes" routes the feedback to the brooder as findings and re-gates after the fix).
2. Merge the branch to main (prefer a regular merge). On conflict, have the brooder rebase its branch and re-run its tests; because the rebase produces hand-resolved changes the skua never saw, route the rebased diff back through the paired skua for a lightweight re-check (tests pass + resolution looks right) before you merge.
3. Run the full test suite on main.
   - **Green:** verify the criteria arrived with the merge — `fledge criteria FTHR-### --json` shows every box checked and `.fledge/molt/FTHR-###.md` exists on main — then run `fledge abandon FTHR-### --fledged`. Commit the spec update, and mark the mirrored team task completed yourself (never rely on a worker to do it). Then remove the worktree (`git worktree remove`) and delete the branch.
   - **Tear down the pair — a required step, not a trailing courtesy.** The feather is not done until its pair is gone. Request graceful shutdown of **both** the brooder and its paired skua by name (`message-peer`) so each can flush any in-flight commit or reply; then **confirm each is gone via your adapter's teammate-shutdown mechanism, forcing termination of any that does not exit promptly** — do not rely on the request alone, since a named worker cannot end its own session and will otherwise linger idle. As each member is confirmed shut down, free its roster slot with `fledge roster release <name>` (e.g. `fledge roster release fledge-brooder-adelie`, then `fledge roster release fledge-skua-adelie`); the pair's species frees for reuse only once both members have been released (§3.1: release on **confirmed shutdown** — observed gone, not merely acked).
   - **Red:** the combination broke — the pair is still alive and the worktree and branch survive (teardown happens only on green). Send the brooder the failure (`message-peer`); it fixes in its worktree and commits to the same branch. Route that fix commit through the paired skua for a lightweight re-check, then merge the fix commit to main and re-run the suite. Loop until green, then proceed to the green teardown above. The fix reaches main only through this merge — never leave it stranded on the (already-merged) branch.
4. Re-evaluate the ready set and dispatch newly unblocked feathers.
5. **Plumage closeout:** run `fledge colony --json` and find this feather's plumage in its `plumages` array; treat the plumage as ready to close only when that entry's `fledged` count equals its `total` (every feather fledged — `done == total`). When it is, first confirm every pair for this plumage's feathers has already been torn down at its green teardown — force-terminate any straggler still present before closing. Then verify each plumage acceptance criterion — citing which feathers and evidence files satisfy it — and present that AC-by-AC accounting through a `confirm-gate` (review). On "Accept", check each box with `fledge criteria check PLM-### <n>` on main, run `fledge status PLM-### fledged`, and commit the spec update. On "Make changes", the gap goes back into the run before the plumage can close.

## 4. Escalations

Workers will escalate blockers and disputes to you. Triage by fledge's standing rule — facts belong in the repo, decisions belong to the user:

- **Facts** (what an interface is, where code lives, what a spec sentence means when the spec is actually unambiguous): resolve yourself by reading the spec, context, and code, and answer the worker.
- **Decisions** (genuine spec gaps, contradictions, tradeoffs, a skua's 3rd-rejection escalation): surface to the user with the context they need, then relay their call.

An escalated brooder stays alive and paused; other feathers keep flowing while it waits.

## 5. End of run

When no feathers remain in the set that are unfinished and dispatchable, verify every pair from the run has been torn down — for any straggler, request shutdown by name and then confirm it is gone, forcing termination via your adapter's mechanism if it does not exit — then reconcile the team task list (Tier C): every team task dispatched this run should be completed — complete any stragglers yourself and note discrepancies. Then report:

- feathers completed (merged, suite green) vs. blocked or escalated, with reasons
- merges performed and the final suite status on main
- any feathers newly unblocked outside the run's scope that could be implemented next

## 6. Recovery after resume

Resume does not restore workers — after a resume, no worker from the transcript exists, regardless of what your notes say. Your adapter's piping file describes its resume behavior; the primitive contract is the real gate, piping is orthogonal. To recover a run:

1. Treat all remembered workers as gone — a resume restores no workers. Don't rebuild the roster from memory: run `fledge roster` to read the current name→feather assignments directly (the roster file persists across the resume), recovering the names that were in use without reconstructing them by hand.
2. Inventory reality: `fledge broods --stale` classifies the held locks for you (it reports the per-lock `worktree` path and `worktree_exists`), plus `fledge broods` (owner, branch, pid-alive per held lock) and `fledge vee` for the fuller picture. Feathers with a held lock (equivalently `status: hatching`) and `worktree_exists: true` are the resume set. The locks `--stale` reports are the release candidates — release each with `fledge abandon FTHR-### --force`, then set its status explicitly (`fledge status FTHR-### pipping --force`) so it re-enters the ready set. Caveat for legacy records: a `--stale` entry whose `worktree` field is empty (a lock brooded before this repo adopted `--worktree`, i.e. predates FTHR-050) was classified stale by convention — an empty path, not a path checked and found gone — so re-check it against `git worktree list` before force-releasing; if that feather's worktree is in fact still present, treat it as a resume, not a release.
3. For each, respawn a fresh **pair** (a new species is fine — one species for both members) into the **existing** worktree and branch. The brooder's spawn prompt must say partial work may exist: inspect commits and the diff before continuing, and re-verify the test-first evidence chain — if the captured failing-test output was lost with the old worker, re-derive it (revert/stash) or flag the gap to the skua. The skua's spawn prompt names its paired brooder and notes an earlier skua may have already checked some AC boxes on the branch — audit rather than assume.
4. Reconcile the team task list against spec frontmatter (complete or create entries as needed).
5. Report the reconstructed roster to the user before proceeding.

For solo tiers, recovery is simpler: re-derive state from `fledge broods` + `git worktree list` + `fledge vee`, resume into existing worktrees, and continue from step 2 of §solo per feather.
