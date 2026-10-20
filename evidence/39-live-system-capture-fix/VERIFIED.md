# VERIFIED — 39-live-system-capture-fix

Verifier re-run on 2026-10-19 at commit 6456e7b (code at 64a07c8; 6456e7b adds
evidence only). Tools came from this worktree's `.venv/bin`.

Red runs used a scratch worktree at the base `86a7b9e` with only the task's
`tests/` diff applied, run with `PYTHONPATH=<scratch>/src`
(`stenographer.__file__` resolved to the scratch `src/`). Mutation runs then
applied the task's `src/` diff there and changed one line at a time. The
scratch worktree was removed afterwards.

Grouped command (V1, V2):
`pytest -q tests/lib/platform/linux/test_system_audio_capture.py tests/lib/live/test_live_session.py::test_live_session_disables_misrouted_pipewire_system_capture`

| Item | Result | Observation |
| --- | --- | --- |
| V1 Capture command and link validation | pass | Red at base: 4 failed. Command test: `At index 1 diff: '--target' != '-P'` (old command, `studio.monitor`). Wrong-link and missing-link tests: `DID NOT RAISE SystemAudioCaptureError`. Tool-missing test: `assert True is False`. Green: 6 passed. Mutations: target back to `{sink}.monitor` → command test failed; link check always true → wrong-link and missing-link tests failed; parser accepts any link source → wrong-link test failed; pre-check drain removed → command test failed (pre-check `9.0` samples reached the callback); no terminate on failure → both failure tests failed (`ProcessLookupError` not raised). |
| V2 LiveSession link failure | pass | Red at base: `assert 'on' == 'off'` at `test_live_session.py:423`. Green: passed. Mutations: link check always true or any source accepted → failed; no terminate → failed with `pw-record stayed alive after the link check failed`. |
| V3 Integration assertions | pass | `pytest --collect-only -m integration tests/lib/platform/linux/test_system_audio_integration.py -q`: `1 test collected`. Not run (R4). |
| V4 Gate | pass | `ruff check .`: `All checks passed!`. `ruff format --check .`: `581 files already formatted`. `pytest -m "not integration"`: `2551 passed, 2 skipped, 6 deselected`. `stenographer --help`: exit 0. |

Grouped counts: base with new tests `5 failed, 2 passed`; fixed `7 passed`.

Notes (do not change the verdict):

- R2 asks for unit tests of the pure parser on the real fixture. The
  `pw-link -l` parser is exercised only through the fake `pw-link` executable
  (start succeeds with the fixture). `parse_pw_dump_output` has no test; it
  runs only when `pw-link` is absent.
- The fixture is a sanitized `pw-link -l` read: hardware names became
  `studio` and `microphone`. Its port names (`monitor_AUX0/AUX1`,
  `input_FL/FR`) match the coordinator observation in the brief.
- The integration test's level check is `rms > 0.0`. The brief's "above
  silence" could mean a dB floor; the manager may want to tighten it before
  the one consented run.
- The added `-P` property `node.name = stenographer-system-capture` is
  explained in V1.md; R1 allows it.
- Two stray fake `pw-record` sleepers from earlier worker runs
  (`/tmp/pytest-of-penguin/pytest-270`, `-271`, old command) were still alive.
  The verifier left them. Three sleepers from the verifier's own
  no-terminate mutation were killed.

No microphone, system audio capture, integration test, `stenographer live`,
or network call ran.
