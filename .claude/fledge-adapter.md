# Claude Code — fledge adapter

fledge's agent-neutral workflow lives at `.fledge/skills/fledge-orchestrate/` (Claude Code discovers it via the `skills` pointer in `.claude/settings.json`). This file maps fledge's 6 orchestration primitives to Claude Code mechanisms.

## Derived tier

**Tier C** — provided: `confirm-gate`, `read-only-shell`, `write-file`, `run-fledge`, `spawn-worker`, `message-peer`.

## Primitive map

| Primitive | Capability | Claude mechanism | Provided | Required for |
|---|---|---|---|---|
| `confirm-gate` | present material, get a structured Accept/Make-changes or option choice | AskUserQuestion | yes | A |
| `read-only-shell` | run read-only shell commands | Bash | yes | A |
| `write-file` | write a file | Write | yes | A |
| `run-fledge` | run any fledge CLI subcommand (incl. all spec mutation) | Bash(fledge ...) | yes | A |
| `spawn-worker` | spawn a fresh, context-free, named, addressable sub-session returning one final message | teammate-spawn | yes | B |
| `message-peer` | send an async by-name message; sender may idle, woken on reply | SendMessage | yes | C |

## Harness piping

For Tier C team-loop runtime behavior (tmux display, `/resume` recovery, permission inheritance, team task list), see `.claude/team-loop.md`.

## Notes

- Spec mutation goes through `run-fledge` (`Bash(fledge …)`); never hand-edit spec frontmatter the CLI can write.
- See `.fledge/skills/fledge-orchestrate/SKILL.md` for routing and ground rules, and `implementation.md` for the phase that matches this tier.
