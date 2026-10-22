# Independent verification: 31-bark-pro-spec

Verdict: **fail**.

Verifier: `t31-verifier-1`. Reviewed worker HEAD `809bb32`.

Read the verifier skill, the task brief through `hive task show
31-bark-pro-spec --brief`, the full approved plan, the task 26 report,
the proposed design authority, and V1-V3. No source file was changed.
No venv was created. No model was downloaded. No microphone was used.

| Item | Result | Observation |
| --- | --- | --- |
| V1: record user decisions and Q1 | pass | Decisions cover Pro-only CPU int8, full Whisper removal, removed and retained keys, conversion and hashes, fail-closed behavior, VAD and padding, ignored old keys, fillers, refine, FIX.md, deleted benches, attribution, dev-only landing, text-only board exemption, and the user-run apt prerequisite. |
| V2: model directory and cache contract | pass | Names all seven files, revision and package pins in the manifest, per-file hashes, and the cache predicate. |
| V2: converter contract | pass | Names the bundled script, input/output CLI, no stenographer import, and exit codes 0-4. |
| V2: backend and config contracts | pass | Keeps Model.transcribe and TranscriptionResult; removes no_speech_prob; defines sherpa token-derived word times, VAD phrase times for live/Files, and the two-field AsrConfig with ignored removed keys. |
| V2: S/A/B/C/D dependencies and gates | fail | The brief requires A after S **and the user's apt step**. The Tasks table lists only S for A. V2 says “A after S; Q1 is now decided”, which does not establish that the user installed python3-venv. The prerequisite appears in decision 14, but the task dependency contract omits it. B/C/D dependencies and the per-task gates are present. |
| V3: exact docs-only gate | pass | Ran `git diff --name-only dev...HEAD` again. Every returned path is under `.hive/spec/bark-pro-asr/`; output below. No Python change, so Python and Go gates do not apply. |
| Source comparison | pass | Read the full approved plan and report. `git show dev:.hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/report.md \| git hash-object --stdin` and `git hash-object .hive/spec/stenographer-hub/tasks/26-bark-eval/evidence/report.md` both returned `2208f3f9069f0d294918b7896b51e4ddfef25cfa`. |
| Whitespace check | pass | `git diff --check dev...HEAD` exited 0 with no output. |

## Gate output

```text
.hive/spec/bark-pro-asr/README.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/brief.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V1.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V2.md
.hive/spec/bark-pro-asr/tasks/31-bark-pro-spec/evidence/V3.md
```

No executable tests or live verification items apply to this docs-only task.
No UI changes were made, so no visual capture is required.

## Required repair

Add the user-run apt step to task A's dependency contract. Keep Q1 recorded
as decided. Do not treat approval of the prerequisite as confirmation that
the user has completed it. Then obtain a fresh independent verification.
