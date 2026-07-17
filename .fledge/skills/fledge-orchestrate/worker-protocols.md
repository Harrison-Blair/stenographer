# Worker protocols

The delegated worker roles, agent-neutral: the planning incubator, and the team-loop (Tier C) brooder and skua. These are spawned workers: a spawn prompt is a worker's entire context (it inherits no conversation history) and must be fully self-contained. A `spawn-worker` is fresh, named, addressable, killable, may idle, and returns one final message.

A worker's spawn prompt tells it which protocol file to follow (incubator, brooder, or skua), its name, the orchestrator's name (the harness-assigned name the orchestrator supplies — address the orchestrator by exactly that name; e.g. on Claude Code it is `team-lead`), and its role-specific fields — for brooders and skuas: feather ID, worktree/branch, evidence-file path, and the paired counterpart's name (same species); for the incubator: the user's feature request verbatim.

Each protocol lives in its own file:

- `incubator.md` — the delegated planner: owns the planning phase end to end; relay envelope, communication rules, drafting, lifecycle.
- `brooder.md` — the feather implementer: test-first protocol, scope discipline, evidence, handoff and fix loop, lifecycle.
- `skua.md` — the paired reviewer: review checks, criteria audit, verdict rules, lifecycle.
