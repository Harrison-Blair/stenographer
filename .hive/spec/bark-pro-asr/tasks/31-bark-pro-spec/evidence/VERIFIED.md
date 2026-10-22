# Independent verification: 31-bark-pro-spec

Verdict: **pass**.

Verifier: `t31-verifier-2`. Reviewed worker HEAD `fe3d351`.
This verdict replaces the previous failed verdict. The previous failure was
an omitted dependency. Task A now explicitly depends on S and the user's
`python3-venv` apt step on the machine that runs A.

Read the verifier skill, the brief from `hive task show
31-bark-pro-spec --brief`, the full approved plan, the task 26 report,
the design authority, and V1-V3. Rechecked each item against the current
spec. V1 and V2 describe the earlier spec; this record describes the current
spec. No source file was changed. No venv was created. No download or
microphone access was needed.

| Item | Result | Observation |
| --- | --- | --- |
| V1: user decisions | pass | Records Pro-only CPU int8, complete Whisper removal, removed and retained keys, local pinned conversion, source and output hashes, fail-closed mismatch, two-run determinism check, VAD and padding, ignored old keys, fillers, refine, FIX.md, bench deletion, attribution, dev-only landing, and the text-only board exemption. |
| V1: Q1 | pass | Records the user-run apt prerequisite, no sudo by agents, venv preflight with non-zero failure and no download, Doctor warning, and the FIX.md apt instruction. |
| V2: model directory and cache | pass | Defines the directory and seven files, manifest revision, package pins, per-file hashes, and cache predicate. |
| V2: converter | pass | Names the bundled asset and task 26 basis, input and output CLI, no stenographer import, and exit codes 0-4. |
| V2: download | pass | Defines preflight checks before network access, pinned CPU packages, source and output hash checks, installation, cleanup on success and failure, and attribution output. |
| V2: backend and config | pass | Keeps Model.transcribe and TranscriptionResult. Removes no_speech_prob. Defines sherpa token-derived word times and retained VAD phrase times for live and Files. Defines the two-field AsrConfig and ignored removed keys without automatic rewrite. |
| V2: tasks and dependencies | pass | S has no dependency. A depends on S and the user's apt step. B depends on A. C depends on B. D depends on A, B, C. Each task has a gate. The prior omission is repaired. |
| V3: exact docs-only gate | pass | Ran `git diff --name-only dev...HEAD` again. Every returned path is under `.hive/spec/bark-pro-asr/`. Output is below. |
| Source comparison | pass | Read the full approved plan and task 26 report. The report on dev and the local report both hash to `2208f3f9069f0d294918b7896b51e4ddfef25cfa`. The spec uses the report's Pro revision, converter basis, CPU runtime, token timing facts, and attribution parties. |
| Whitespace | pass | Ran `git diff --check dev...HEAD`. Exit 0, no output. |

## Gate output

```text
.hive/spec/bark-pro-asr/README.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/brief.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V1.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V2.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V3.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/VERIFIED.md
```

The brief specifies a docs-only gate. Python and Go gates do not apply.
There are no executable test or live items for this task, so no red/green
run applies. This task changes no UI; no visual capture applies. Runtime
behavior, package pins, output determinism, and installation are for the
later implementation tasks. The apt installation status is recorded in the
spec; this verification did not create a venv to repeat that check.

No temporary files or resources were created.
