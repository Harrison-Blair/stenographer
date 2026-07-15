# Claude Code — fledge team-loop piping

Harness runtime behavior for fledge's Tier C team loop on Claude Code. The workflow *logic* (brooder/skua pairing, fix loop, merge gating, recovery steps) lives in the agent-neutral core skill at `.fledge/skills/fledge-orchestrate/implementation.md`; this file covers only how Claude Code realizes the piping. For each primitive's mechanism mapping, see `fledge-adapter.md` in this directory.

## Teammate display (tmux)

`fledge init` wrote `.claude/settings.json` with `teammateMode: tmux` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Teammates (brooders and skuas) run in their own tmux panes so you can watch them work.

**Precondition:** the session is inside tmux (`test -n "$TMUX"`). This auto-resolves with no `confirm-gate` — tmux present → proceed with panes; tmux absent → proceed degraded with in-process teammates (no panes; teammates still run). Report which path was taken as one line of plain, non-blocking run narration (not a gate, no wait for a response), e.g. "tmux detected — spawning teammates in panes" or "tmux not detected — proceeding degraded, in-process teammates".

## Orchestrator name (how teammates reach you)

The agent-neutral skill calls you `fledge-orchestrator`; on Claude Code that role **is** the team lead, and the harness registers the lead under the fixed name **`team-lead`** — you cannot rename yourself. `team-lead` is the name teammates must use to `SendMessage` you; `fledge-orchestrator` is not a routable address here. So whenever a spawn prompt or protocol says to give a worker "your name (the orchestrator's name)", pass **`team-lead`**. (`fledge-orchestrator` still appears as the `fledge brood --owner` lock label, which is an audit tag, not a message address — leave it.)

## Spawning and addressing teammates

- Spawn a teammate of a given agent type (e.g. `fledge-brooder`) named per the penguin-species scheme in `implementation.md` §3.1. The teammate's agent definition (`.claude/agents/fledge-<role>.md`) is its system prompt; the spawn prompt you pass is its task context. Both are the teammate's entire context — it inherits no conversation history.
- Address a teammate by name via `SendMessage`. A teammate may go idle; idle is not completion. It stays alive and addressable until you shut it down (see "Shutting down teammates" below).
- Teammates inherit your permission mode at spawn. Brooders must edit files and run tests unattended in their panes — `implementation.md` §1 surfaces the current mode via a `confirm-gate` and asks whether to proceed or stop while the user switches to a mode without per-action prompts (e.g. `acceptEdits`). Without this, brooder panes stall awaiting approvals.

## Shutting down teammates

This is the Claude Code realization of the core skill's teammate teardown (`implementation.md` §3.2 green teardown, §3.2 plumage closeout, §5). Get it right or pairs linger.

- **A `SendMessage` shutdown request does not, by itself, terminate a teammate.** Named teammates do not self-exit — a request can only prompt an acknowledgement and leave the teammate idle in its pane. Idle is not gone.
- **`TaskStop <name>` is what actually terminates a teammate.** Use it as the real teardown mechanism, not merely an escalation.
- **Procedure per worker** (do this for the brooder *and* its paired skua at green teardown): first `SendMessage` the graceful shutdown request by name (lets it finish an in-flight commit or reply and reach quiescence), then `TaskStop <name>` to actually terminate it. Issue the `TaskStop` regardless of whether the teammate acked — do not wait indefinitely for a reply.
- **Confirmed shutdown** = the teammate no longer appears in the team roster and its tmux pane has closed. That observed absence — not the teammate's acknowledgement — is what frees its species for reuse (`implementation.md` §3.1). If a teammate does not quiesce, `TaskStop` it anyway and confirm it is gone.

## Planning delegation

The planning phase (`planning.md` §0) is delegated to a `fledge-incubator-<species>` teammate; you are a pure relay and hold no planning context. Two Claude Code specifics:

- Relay each `GATE`/`QUESTION` message from the incubator to the user via AskUserQuestion, verbatim and in full, and SendMessage the user's choice (and any feedback) back verbatim. Never answer on the user's behalf.
- Teammates cannot spawn teammates: when the incubator needs a forager it sends you a `SPAWN-REQUEST`; spawn the `fledge-forager-<species>` teammate yourself with exactly the spawn prompt provided (it names the incubator as the report target), then confirm back to the incubator.

## The team task list

You are the **sole writer** of the shared team task list. Create one team task per dispatched feather titled `FTHR-###: <title>`, assigned to that brooder teammate, state in-progress. Workers never create, claim, or update entries. Mark a task completed yourself when its feather merges green. The task list is a visibility mirror only; spec frontmatter is the source of truth and wins on any disagreement.

## Recovery after resume

`/resume` and `/rewind` do not restore teammates — after a resume, no teammate from the transcript exists, regardless of what your notes say. `implementation.md` §6 is the recovery procedure; on Claude Code specifically:

1. Treat all remembered teammates as gone; clear the roster.
2. Inventory reality: `git worktree list`, feather branches, `fledge broods` (owner, branch, pid-alive), `fledge vee`. Resume set = held lock + surviving worktree.
3. Respawn a fresh brooder+skua **pair** (a new species is fine — one species for both) into the **existing** worktree and branch; the brooder's spawn prompt must say partial work may exist, and the skua's must note an earlier skua may have already checked some AC boxes on the branch.
4. Reconcile the team task list against spec frontmatter.

Manual reconstruction via `fledge vee` + `fledge broods` + `git worktree list` is the resume method; `/resume` does not restore the team.

## Skill loading

The core skills live at `.fledge/skills/` (fledge-owned, committed). Claude Code only discovers project skills under `.claude/skills/`, and it follows symlinked skill directories, so `fledge init` creates one symlink per core skill (e.g. `.claude/skills/fledge-orchestrate` → `../../.fledge/skills/fledge-orchestrate`).

(One pointer to the single source — do not copy the skill into `.claude/skills/`; that creates the duplicate `fledge init`'s guard refuses. Symlinks there are recognized and left alone.)
