# Context document conventions

Applies to all files the `fledge-forager` writes into `.fledge/nest/` (the eight concern docs and `index.md`).

## Frontmatter (all files)

Frontmatter is stamped by the CLI (`fledge nest scaffold` on creation; `fledge nest stamp <file>` to refresh). The binary is the single source of the schema — do not restate it here.

## Concern docs

- Title: `# <Concern>` followed by a one-paragraph scope statement.
- Organized by topic, not by source module (except `modules.md`, which is organized by module).
- Every claim references the file(s) it came from: `path/to/file.go:Symbol`.
- End with `## Open Questions` if any scout uncertainties survived synthesis; omit the section otherwise.
- `modules.md` entries follow: module name → purpose → key files → "Look here for: …".

## index.md

```markdown
---
<frontmatter stamped by fledge nest scaffold / fledge nest stamp>
---

# Context Index

## <doc>.md
2–3 sentence summary of what this document actually contains for THIS repo.
Read this when: <the situations where loading this doc pays off>.
```

One entry per concern doc, in a stable order (architecture, modules, conventions, data-model, dependencies, entry-points, testing, domain). Downstream agents read only the index by default and load docs based on the `Read this when:` lines — write those lines as routing rules, not descriptions.
