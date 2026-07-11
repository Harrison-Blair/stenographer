# Feather template

This file documents the feather (task) format. Files are created with `fledge new feather` (the canonical skeleton is embedded in the binary); never instantiate this template by hand — the CLI allocates the ID, links the plumage, computes the initial pipping/egg hint, and stamps the frontmatter.

Feathers live at `.fledge/pluma/feathers/FTHR-###-<kebab-name>.md`. IDs are zero-padded and next-sequential within the folder. Every feather links to exactly one plumage. `depends_on` forms blocking relationships: a feather is `pipping` only when every feather in `depends_on` is `fledged`.

```markdown
---
id: FTHR-003
title: <feather title>
plumage: PLM-001
status: egg            # egg | pipping | hatching | fledged
priority: P1           # P0 | P1 | P2 | P3
depends_on: [FTHR-001, FTHR-002]   # [] when unblocked from the start (then status: pipping)
oversight: merge       # optional; omit for fully autonomous implementation
                       # merge  = implement & review normally, but hold the branch unmerged
                       #          until the user signs off on the diff + skua verdict
                       # during = prompt the user to confirm they are ready BEFORE spawning
                       #          the brooder, so they can participate during the work
authored: <UTC ISO 8601>
agent: fledge-orchestrate/planning
fledge_version: <VERSION file contents>
---

# FTHR-003: <feather title>

## Description
What this feather delivers, scoped so one engineer/agent can complete it in a single focused effort.

## Affected Modules
Modules and key files involved, citing the context docs consulted (e.g. "see .fledge/nest/modules.md → internal/graph").

## Approach
Implementation guidance: intended shape of the change, constraints, existing code to reuse. Feathers MAY contain implementation detail (unlike plumages). The design must be testable: seams, injectable dependencies, and observable outputs the tests below can hook into.

## Tests
The tests that prove this feather's behavior, written test-first:
- Name each test and the behavior it pins down (map to the acceptance criteria below).
- Implementation order is fixed: (1) write the tests; (2) run them against the unchanged code and confirm they FAIL for the expected reason; (3) implement until they pass. A test that has only ever been seen passing proves nothing.

## Acceptance Criteria
Checkbox list, one `- [ ] AC-N: …` line per criterion — authored unchecked; checked only via `fledge criteria check` (never hand-edited), with per-criterion evidence in `.fledge/molt/FTHR-003.md`. Reference the parent plumage's criteria where applicable (e.g. "satisfies PLM-001 FC-2"). AC-1 is always:
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: …
```
