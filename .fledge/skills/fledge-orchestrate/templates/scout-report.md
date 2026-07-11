# Scout report template

Raw module reports written by `fledge-context-scout` to `.fledge/nest/raw/<module>.md`. The CLI creates the file with the correct frontmatter and section skeleton via `fledge nest scout --module <module>` — the binary is the single source of the schema. Scouts fill every section body in the created file; write `None observed.` where a section is empty, never omit a section.

Section order (for reference): Purpose · Structure & Key Files · Entry Points & Public Interfaces · Data Types · External Dependencies · Conventions Observed · Tests · Domain Terms · Open Questions.
