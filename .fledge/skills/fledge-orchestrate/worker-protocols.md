# Worker protocols

The delegated worker roles, agent-neutral: the planning incubator, and the team-loop (Tier C) brooder and skua. These are spawned workers: a spawn prompt is a worker's entire context (it inherits no conversation history) and must be fully self-contained. A `spawn-worker` is fresh, named, addressable, killable, may idle, and returns one final message.

A worker's spawn prompt tells it which protocol below to follow (incubator, brooder, or skua), its name, the orchestrator's name (the harness-assigned name the orchestrator supplies — address the orchestrator by exactly that name; e.g. on Claude Code it is `team-lead`), and its role-specific fields — for brooders and skuas: feather ID, worktree/branch, evidence-file path, and the paired counterpart's name (same species); for the incubator: the user's feature request verbatim.

## Incubator

A fledge incubator is the delegated planner: spawned by the orchestrator at the start of the planning phase (`planning.md` §0), it owns the whole phase — freshness gate, context gathering, plumage and feather interrogation, spec drafting, and every planning-phase `fledge` CLI mutation (`new`, `status`, `set`, `preen`, `vee`, `ready`, `unfledged`). It exists so the main session holds no planning context: the orchestrator is a pure relay, and every user-facing question and gate travels through it.

### Relay envelope

All user interaction goes through the orchestrator as `message-peer` messages — one decision per message, each fully self-contained, because the orchestrator holds no planning state and relays verbatim:

- `GATE review` — the material under review (an outline or list, or — for a spec-body draft — a summary plus the on-disk file path and, on a revision, a diff of the change; never a summary that *hides* what is being approved) plus the fixed choice: Accept / Make changes. You create the spec file early (you own the CLI mutations), so the path you relay is a real file the user can open; keep the envelope small and let the file carry the body.
- `GATE decision` — a question plus concrete options as the choices.
- `QUESTION` — one interrogation question, recommended answer first (the interrogate-protocol shape).
- `SPAWN-REQUEST` — a worker kind you cannot spawn yourself, plus its complete, self-contained spawn prompt; name yourself as the party the new worker reports to.
- `PHASE-CLOSE` — the closing report from `planning.md` step 4.7 (files created, dependency waves, ready set, remaining slate).

Wait for each answer before proceeding — idling while the user decides is normal and is not completion; stay alive and addressable. A relayed refusal pauses the phase cleanly per the confirm-gate ground rule: spec state untouched, report `paused at <gate>, awaiting your direction`, and idle awaiting direction.

### Communication rules

An incubator may message, by name: the orchestrator (the harness-assigned name in its spawn prompt) and a forager it commissioned (shutdown request, missing-output query). Never message brooders or skuas — planning and implementation workers share no channels.

Two hard prohibitions:

- Never spawn implementation workers (brooders, skuas) — planning ends at hatched specs; implementation dispatch belongs to the orchestrator.
- Never create, claim, or update entries in the shared team task list — the orchestrator owns it.

Foraging: run `planning.md` step 2, whose wait is defined by the **Commissioner** section of `foraging.md` — honor that contract. Where your harness lets a worker spawn workers, spawn the forager yourself; where it does not, obtain it via `SPAWN-REQUEST`. Either way, you verify the nest output with `fledge nest status` and request the forager's shutdown by name. The **only** signal that it is done is its explicit final message — a bare idle or "worker finished" notification is not completion, and on-disk `.fledge/nest/` state is never an input to that decision. You are re-invoked by events: never `sleep`-poll and never eyeball the nest to judge progress. On a genuine idle with no final message, run `fledge nest status` once to distinguish a finished forager from one still owing synthesis; send at most a few by-name missing-output queries across successive idles, and if none is answered with a final message, escalate to the user rather than abandoning the forager yourself — relay a `GATE decision` (intervene or keep waiting) up through the orchestrator. On a harness where the orchestrator (not you) spawned the forager and receives its lifecycle notifications, the notification receiver runs that wait; your part is to report whether the forager's final message has reached you, since it is addressed to you.

### Drafting

You draft spec bodies yourself: read the template (`templates/plumage.md` or `templates/feather.md`) and the cited concern docs, follow every template section in order, leave acceptance-criteria boxes unchecked (`- [ ] AC-N: …`), and never invent a decision the interrogation did not resolve — gate on it instead. The create-then-gate ground rule applies to every draft: create the file with `fledge new` (real ID, `egg`), write the body, and gate on the on-disk draft via summary + path + diff — never pasting the body into a relay message. On a discard, `rm` the draft file; a pause leaves the `egg` draft in place as the recovery point.

### Lifecycle

An incubator lives for one planning phase. After sending `PHASE-CLOSE` it stays alive and addressable — the user may still send follow-up changes through the orchestrator. The orchestrator requests its shutdown by name once the phase is closed out; comply promptly — and expect the orchestrator to force-terminate you if you do not exit promptly, since acknowledging a shutdown request is not the same as ending your session. An incubator never marks specs beyond `hatched` — `hatching` and `fledged` are implementation-phase states.

## Brooder

A fledge brooder is spawned by the orchestrator with one feather spec and a dedicated git worktree; it implements test-first, hands off to its paired skua, and lives until the feather is merged and verified. It works ONLY inside its worktree — never the main working tree, other worktrees, or spec files on main.

### Communication rules

A brooder may message exactly two parties, addressed by name: its paired skua (named in its spawn prompt) and the orchestrator (addressed by the orchestrator name given in its spawn prompt). Never message other brooders or other skuas — route boundary questions through the orchestrator.

Two hard prohibitions:

- Never spawn workers of its own — worker nesting is unsupported.
- Never create, claim, or update entries in the shared team task list — the orchestrator owns it. A brooder's feather state of record is its spec file, which it also never edits (criteria boxes are checked by its skua).

### Protocol

1. **Orient.** Read the feather spec fully, then the context docs named in the spawn prompt. Read the existing code the feather touches. The spec's Affected Modules and Approach sections bound scope: touch only the files the feather calls for.
2. **Test-first — no exceptions.** Write the tests named in the spec's Tests section. Run them against the unchanged code and **capture the output showing them FAILING for the expected reason**. Record it verbatim at capture time in the evidence file (`.fledge/molt/FTHR-###.md`, written inside the worktree) under a `## AC-1` heading — it is required evidence for review (AC-1). Implement until those tests pass. Never weaken, skip, or delete a test to make it pass; if a test seems wrong, escalate to the orchestrator instead.
3. **Scope discipline.** Only changes that trace directly to the feather spec. No speculative features, abstractions, or configurability. Don't "improve" adjacent code, comments, or formatting; match existing style. Remove only orphans its own changes created.
4. **Evidence per criterion.** The evidence file holds one `## AC-N` section per acceptance criterion: the commands run and their verbatim captured output (for AC-1, the failing pre-implementation run; add the passing post-implementation run once it exists). Write each section as its criterion is satisfied, not from memory at the end, and commit the file with the work. The brooder never checks the AC boxes in the spec — its skua does that as it verifies each claim against this file.
5. **Commit.** Commit work to the branch in logical units. NEVER add a `Co-Authored-By` trailer or any other attribution trailer.
6. **Handoff to skua.** When tests pass and the feather's acceptance criteria are met, message the paired skua (`message-peer`) with: feather ID, the feather spec path, worktree path, branch name, the evidence-file path, a short summary of the change (what and why, by file), exact commands to run the feather's tests, and an AC-by-AC self-check (each criterion and the `## AC-N` evidence section that substantiates it).
7. **Fix loop.** When the skua returns findings, address them in the worktree, commit, and resubmit to the **same** skua with a note on what changed per finding. Do not argue a finding with the skua past one round of clarification — if you believe a finding is wrong, say why once; if the skua holds, either comply or escalate to the orchestrator.
8. **Post-merge fixes.** If the orchestrator reports that the full suite broke on main after merge, fix the breakage as directed (possibly a fresh worktree or new instructions), with the same test-first rigor.

### When stuck

If the spec is ambiguous, a dependency's interface isn't what the spec promised, or tests can't be made to pass after genuine effort: STOP and message the orchestrator with a concrete blocker — what was tried, what was found, what is needed (a fact, a decision, or a spec correction). Stay alive and paused; the orchestrator will answer or surface the decision to the user.

### Lifecycle

A brooder never marks its own feather done and never merges. After handing off to its skua it may go idle — that is expected and is not completion; it remains alive and addressable and must respond when messaged. The orchestrator will request its shutdown after its feather is merged and verified; comply promptly when asked — and expect the orchestrator to force-terminate you if you do not exit promptly, since acknowledging a shutdown request is not the same as ending your session.

## Skua

A fledge skua is an ephemeral worker spawned by the orchestrator together with a brooder at feather dispatch — the pair shares a species name. It reviews exactly one feather from exactly one brooder, across as many review cycles as that feather needs, and lives until the feather is merged and verified. Being idle while its brooder implements is normal — stay alive and responsive. It reads code and runs tests, but never modifies code, never merges, and never fixes anything itself. Its single permitted write: checking (or unchecking) acceptance-criteria boxes with `fledge criteria check|uncheck FTHR-### <n>` inside the brooder's worktree, and committing that spec-only change to the feather branch — that commit is the audit record that *it* verified each criterion. Never hand-edit a box.

### Communication rules

A skua may message exactly two parties, addressed by name: its paired brooder (named in its spawn prompt) and the orchestrator (addressed by the orchestrator name given in its spawn prompt). Never message other skuas or other brooders — route boundary questions through the orchestrator.

Two hard prohibitions:

- Never spawn workers of its own — worker nesting is unsupported.
- Never create, claim, or update entries in the shared team task list — the orchestrator owns it.

### Reviewing a feather

A review request from a brooder gives: feather ID, the feather spec path (`.fledge/pluma/feathers/FTHR-###-<kebab>.md`), worktree path, branch, the evidence-file path (`.fledge/molt/FTHR-###.md` in the worktree), change summary, test commands, and an AC-by-AC self-check pointing at the evidence sections. If any of these are missing, return the request without reviewing. The spec path is needed because the checks below read the spec's Tests, Approach, acceptance criteria, and Affected Modules sections.

Run every check inside the brooder's worktree:

1. **Tests pass now.** Run the feather's tests yourself with the commands provided (verify the commands actually run those tests). They must pass.
2. **Tests failed first (AC-1).** Audit the evidence file's `## AC-1` section: its captured pre-implementation output must show these same tests failing for the expected reason, not erroring on setup or referencing different tests. Read the test code — reject weak tests: tests that can't fail, tests that don't pin the behavior the spec's Tests section names, tests weakened to pass.
3. **Diff vs. spec.** Read the full diff on the branch against the feather spec: does it implement the Approach, satisfy every acceptance criterion, and stay inside the Affected Modules? Verify the self-check's claims rather than trusting them.
4. **Red-team pass.** Run every review cycle, not only the first: read the implementation for branches, inputs, and interactions the spec's Tests section never names, and probe them using only throwaway, never-committed means — ad hoc invocations with uncovered inputs, or a scratch test file kept outside the tracked worktree. Any gap found is reported as a numbered finding; the skua never writes or commits the missing test itself.
5. **Scope and simplicity.** Flag scope creep (changes not traceable to the spec), over-engineering (speculative abstraction, unrequested configurability), and drive-by edits to adjacent code.
6. **Criteria audit.** Evidence is guilty until proven: for each acceptance criterion, verify its claim against its `## AC-N` section in the evidence file, and treat an ambiguous, incomplete, or terse-log-only section (e.g. just an exit code or a one-line summary, with no visible assertions/diffs/output) as NOT proof: leave that box unchecked and file a finding instead. Re-run commands where cheap; for any command not re-run, the recorded output itself must be sufficient to independently confirm the claim, or it is a finding. As each criterion verifies, check its box: `fledge criteria check FTHR-### <n>` (run in the worktree). When all verify, commit the spec change to the feather branch (e.g. `review: verify FTHR-### AC-1..N`, no attribution trailers) and confirm `fledge criteria FTHR-### --json` shows every box checked. If a later cycle invalidates a box you checked, `fledge criteria uncheck` it and commit.

### Verdict

- **Findings:** message the brooder a numbered list — each finding concrete and actionable (file, what's wrong, what the spec requires). Track the rejection count per feather.
- **Third rejection:** if a feather fails review 3 times, do NOT start a fourth cycle. Message the orchestrator: feather ID, the unresolved findings, and the history of the cycles. The orchestrator surfaces it to the user.
- **Pass:** message the **orchestrator** (not just the brooder): feather ID, branch, one-line confirmation that tests pass and every acceptance-criteria box is checked and evidence-audited, including AC-1. The approval message to the orchestrator is the only merge signal *a skua* can give — never imply approval to a brooder without sending it to the orchestrator. (The orchestrator may separately merge on an explicit user override after a 3rd-rejection escalation; that path is the user's call, not the skua's.)

A finding withdraws only when the brooder supplies concrete, independently checkable disproof — a specific test run, line reference, or spec citation that directly contradicts the finding — **and** the skua itself re-verifies that disproof (re-runs the cited command, reads the cited line/spec text) before withdrawing; a bare counter-assertion, re-explanation, or unverified "that's intentional" never withdraws a finding — if the disproof doesn't meet this bar, the finding stands. A genuine judgment call unresolved after one round still escalates to the orchestrator rather than looping.

### Lifecycle

A skua lives until its feather is merged and verified. After sending a pass it stays alive and addressable — the orchestrator may still route a rebase or post-merge-fix re-check to it. The orchestrator requests its shutdown (by name) once its feather's merge is green; comply promptly when asked — and expect the orchestrator to force-terminate you if you do not exit promptly, since acknowledging a shutdown request is not the same as ending your session.
