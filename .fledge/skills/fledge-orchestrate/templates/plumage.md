# Plumage template

This file documents the plumage (requirement) format. Files are created with `fledge new plumage` (the canonical skeleton is embedded in the binary); never instantiate this template by hand — the CLI allocates the ID, names the file, and stamps the frontmatter.

Plumages live at `.fledge/pluma/plumage/PLM-###-<kebab-name>.md`. IDs are zero-padded and next-sequential within the folder. Plumages capture the WHAT and WHY at feature level — never implementation details (no file paths, no function names, no technology choices unless they are themselves the plumage).

```markdown
---
id: PLM-001
title: <feature title>
status: egg            # egg | hatched | fledged
priority: P1           # P0 | P1 | P2 | P3
authored: <UTC ISO 8601>
agent: fledge-orchestrate/planning
fledge_version: <VERSION file contents>
---

# PLM-001: <feature title>

## Context
The broader picture: why this feature is needed, what prompted it, how it fits the product.

## User Stories
- As a <role>, I want <capability>, so that <benefit>.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: …
2. FC-2: …

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered done, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` (never hand-edited) at plumage closeout, when the orchestrator verifies each criterion against the completed feathers with the user.
- [ ] AC-1: …

## Out of Scope
What this plumage deliberately does not cover.

## Open Questions
Unresolved items carried out of interrogation, if any.
```

Lifecycle: written as `egg` during interrogation; set to `hatched` on explicit user sign-off; `fledged` when all linked feathers are fledged and every acceptance-criteria box is checked (`fledge status PLM-### fledged` refuses while boxes are unchecked; `fledge preen` errors on a fledged plumage with unchecked boxes).
