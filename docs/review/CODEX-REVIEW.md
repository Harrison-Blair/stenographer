# Codex Review

Reviewed the complete working-tree change against `HEAD` (`31c1f98`), including
untracked source/tests and the deleted cue asset. The binding repository rules in
`AGENTS.md`, `CLAUDE.md`, and `docs/reauthor.md` were applied. The changed production
code was also checked against every item in [`docs/code-smells.md`](../code-smells.md).

## Code-review findings

### REVIEW-001 — [P2] Keep compositor probing out of unit construction

- Evidence: `src/stenographer/daemon.py:257` and the unmarked build tests at
  `tests/test_daemon.py:135-166`
- Scenario: the normal non-integration suite calls `Daemon.build()`, which now performs
  a real Wayland registry connection through `detect_clipboard_backend()`.
- Impact: unit tests are no longer pure/sandbox-independent and can touch the user's
  graphical session. Probe failure is swallowed, so the suite can stay green while
  exercising different external behavior on different machines.
- Recommendation: select the real backend in an integration-wired startup boundary and
  pass the selected enum into construction; keep unit coverage on `pick_backend()`.
- Rule: [`AGENTS.md:44-49`](../../AGENTS.md) requires unit tests to cover pure logic only.

### REVIEW-002 — [P2] Refresh the overlay for repeated start errors

- Evidence: `src/stenographer/daemon.py:268-274`
- Scenario: microphone start fails, the mailbox auto-hides the error after 2.5 seconds,
  and a later key press fails to start the microphone again without any intervening
  daemon display state.
- Impact: `_overlay_state` remains `ERROR` after the mailbox/helper timeout, so the
  duplicate suppression drops the second error publication and the pill does not show
  that failure. The cue and notification still occur, limiting the impact to the
  optional visual feedback.
- Recommendation: do not suppress `ERROR` refreshes, or synchronize daemon-side state
  with the timeout-driven hide.
- Rule: `docs/reauthor.md:287-288` requires operational errors to show for 2.5 seconds.

### REVIEW-003 — [P2] Clear an unstarted warm-up thread before teardown

- Evidence: `src/stenographer/daemon.py:301-305,477-479`
- Scenario: `Thread.start()` raises `RuntimeError` (for example, thread-resource
  exhaustion), which this code intentionally catches.
- Impact: `_warmup_thread` still points to a never-started thread; `Daemon.stop()` then
  calls `join()` on it and raises `RuntimeError: cannot join thread before it is
  started`, contradicting the method's idempotent/never-fragile teardown contract.
- Recommendation: assign the field only after a successful start, or clear it in the
  exception path.

## Code-smell audit findings

<a id="audit-001"></a>
### AUDIT-001 — DI-02 Duplicate Code

- Impact: medium
- Confidence: high
- Evidence: `src/stenographer/overlay_wayland.py:185-191,485-549` and
  `src/stenographer/overlay_x11.py:383-389,623-715`
- Match: both backends independently store the same loading/spectrum state, calculate
  the same elapsed pulse phase, handle the same two protocol message types, and
  schedule the same repaint deadline. The copies differ mainly at the final backend
  presentation call.
- Consequence: pulse timing, reset ordering, or spectrum behavior must be changed and
  tested twice; this patch already required parallel edits in both backend classes.
- Recommendation: [`MF-03 Extract Class`](../refactoring-techniques.md#extract-class) —
  move the shared display-activity state and transition/deadline policy into one
  helper, leaving each backend responsible only for presenting its current frame.
- Context check: backend-specific Wayland/X11 resource management should remain
  separate; only the newly duplicated protocol/display policy is a shared change rule.
- Related: `BL-05 Data Clumps`, `CP-03 Shotgun Surgery`
- Catalog support: [`docs/code-smells.md:158-166`](../code-smells.md#duplicate-code)

<a id="audit-002"></a>
### AUDIT-002 — DI-04 Dead Code

- Impact: low
- Confidence: high
- Evidence: `src/stenographer/status.py:258-270,310-314` and
  `src/stenographer/overlay.py:132-135`
- Match: all production consumers were migrated to `DisplayMessageGate` and the new
  mailbox queueing, leaving `GenerationGate`, `coalesce_latest_state`, and the mailbox
  `loading_active` accessor referenced only by tests or not at all.
- Consequence: obsolete protocol-v1-era policy remains part of the apparent status API
  and must be distinguished from the live protocol-v4 path by every maintainer.
- Recommendation: delete the obsolete helpers/accessor and their tests; version control
  already preserves them. This is the catalog's direct treatment for proven dead code.
- Context check: the package is an application rather than a compatibility-promised
  library, the protocol version was deliberately changed, and repository-wide search
  found no configuration, reflection, plugin, or production references.
- Catalog support: [`docs/code-smells.md:187-194`](../code-smells.md#dead-code)

## Scope

- Production/configuration files: `scripts/{build,install,progress}.sh`, the changed and
  untracked top-level modules under `src/stenographer/`, `_version.py`, and the deleted
  `assets/sounds/model_loading.wav`.
- Tests: every changed/untracked file under `tests/`, including all smoke-test changes.
- Documentation/instructions: `AGENTS.md`, `CLAUDE.md`, `README.md`, and
  `docs/reauthor.md`.
- Context-only files: `docs/code-smells.md`, `docs/refactoring-techniques.md`,
  `pyproject.toml`, `packaging/stenographer.spec`, unchanged imported modules, and the
  `HEAD` versions of changed files. No finding is reported against a context-only file.
- Limitations: the opt-in real-machine integration suite was not run; no microphone,
  uinput device, compositor, xclip/wl-copy round trip, or real ASR model was exercised.
  `shellcheck` was unavailable. The repository venv is Python 3.14, so Python 3.12
  compatibility was checked through Ruff's configured `py312` target rather than by a
  3.12 interpreter.

## Code-smell coverage

| Criterion | Result |
|---|---|
| BL-01 Long Method | No finding — expanded routines remain cohesive linear boundary/render loops; length alone was not treated as evidence. |
| BL-02 Large Class | No finding — large daemon/backend classes are documented resource-lifetime or orchestration boundaries; the separable duplication is reported under [AUDIT-001](#audit-001). |
| BL-03 Primitive Obsession | No finding — strings/integers are primarily validated config or strict serialization fields. |
| BL-04 Long Parameter List | No finding — the longer signatures are explicit pure rendering/boundary data, and hiding them would add coupling. |
| BL-05 Data Clumps | Finding — the repeated loading/spectrum field cluster supports [AUDIT-001](#audit-001). |
| OA-01 Alternative Classes with Different Interfaces | No finding — both display backends expose the same `backend`, `run`, and `close` contract. |
| OA-02 Refused Bequest | Not applicable — no changed subtype rejects an inherited contract. |
| OA-03 Switch Statements | No finding — message dispatch is over a small, closed protocol and belongs at the parser/backend boundary. |
| OA-04 Temporary Field | No finding — conditional loading fields have explicit lifecycle checks; their duplication, not conditional validity, is the defect. |
| CP-01 Divergent Change | No finding — orchestration and backend resource ownership remain intentional primary responsibilities. |
| CP-02 Parallel Inheritance Hierarchies | Not applicable — no synchronized subtype hierarchies exist. |
| CP-03 Shotgun Surgery | Finding — parallel backend edits support [AUDIT-001](#audit-001). |
| DI-01 Comments | No finding — comments record concurrency, privacy, protocol, or platform rationale rather than translating unclear code. |
| DI-02 Duplicate Code | Finding — [AUDIT-001](#audit-001). |
| DI-03 Data Class | No finding — dataclasses are immutable messages/config/DTOs at deliberate boundaries. |
| DI-04 Dead Code | Finding — [AUDIT-002](#audit-002). |
| DI-05 Lazy Class | No finding — thin enums/messages/adapters preserve strict protocol or OS boundaries. |
| DI-06 Speculative Generality | No finding — new seams have current production variants or documented behavior. |
| CO-01 Feature Envy | No finding — cross-object access occurs in intentional orchestration/mapping code. |
| CO-02 Inappropriate Intimacy | No finding — private access is confined to smoke diagnostics/test seams, not production coupling. |
| CO-03 Incomplete Library Class | No finding — PyWayland/Xlib compatibility code is localized and not repeated as an awkward workaround. |
| CO-04 Message Chains | No finding — chains are short boundary calls or intentional immutable transformations. |
| CO-05 Middle Man | No finding — supervisor and delivery wrappers add isolation, ordering, policy, and resource ownership rather than forwarding alone. |

## Verification

- `.venv/bin/ruff check .` — passed
- `.venv/bin/ruff format --check .` — passed
- `.venv/bin/pytest -m "not integration"` — 305 passed, 9 skipped, 4 deselected
- `.venv/bin/stenographer --help` — passed
- `git diff --check` — passed

## Summary

The review found three behavioral/test-policy issues (all P2), one medium-impact
duplication smell, and one low-impact dead-code smell. The most useful sequence is:
first restore pure daemon construction for unit tests, fix error/thread teardown state,
extract the shared backend display policy, and finally remove the obsolete status
helpers. Passing unit checks does not replace the required real-machine smoke suite.
