# 56-asr-defaults verification

Verifier: independent re-run on 2026-10-20 against `d56ad31` (base `db2159b`).
The worktree has no `.venv`, so a temporary symlink to
`/home/penguin/source/stenographer/.venv` was used with `PYTHONPATH=src`. The
loaded package was this worktree's `src/stenographer`. Base and mutation copies
of `src/` lived in the session scratchpad and were removed after this file was
written. No model download, microphone, `live`, `run` or integration test ran.

| Item | Result | Re-run and observation |
| --- | --- | --- |
| V1 default and config compatibility | pass | Red: the four focused tests against base `src/` (`git archive db2159b`) gave `3 failed, 1 passed`; the default and unset-model tests returned `dropbox-dash/...`. The explicit legacy-model test passes at base by design (compatibility already held). To show it is not tautological, a mutated loader that replaces an explicit `asr.model` with the default made it fail (`1 failed`). Green at HEAD: `4 passed`. |
| V2 download default | pass | Red at base: `model download --asr` selected and printed `dropbox-dash/faster-whisper-large-v3-turbo` (assertion failed). Green at HEAD: passed; the download function is replaced, so nothing was fetched. |
| V3 generated config, Doctor, docs | pass | `STENOGRAPHER_CONFIG=<tmp>/config.toml stenographer setup --default` wrote the file; grep found `model = "deepdml/faster-whisper-large-v3-turbo-ct2"`. Doctor tests `test_render_missing_capability_carries_fix_hint` and `test_probe_uses_model_cache_service_and_keeps_display_optional`: `2 passed`. README, `docs/usage.md`, `docs/building.md`, `site/index.html` and CHANGELOG name the deepdml default; README, usage and site link the anchor `#cpu-model-and-context-screen-2026-10-20`, which matches the heading at `docs/transcription-experiments.md:543`. Remaining `dropbox-dash` references: historical CHANGELOG entry, the legacy-config test fixture, and the bench `download_models.py` candidate list. Hotwords comment kept, value `""`. The "about 1.6 GB" size text matches the cached deepdml repo (`du -shL` 1.6G). |
| V4 gate | pass | `ruff check .`: All checks passed. `ruff format --check .`: 597 files already formatted. `pytest -m "not integration"`: 2566 passed, 2 skipped, 6 deselected. `stenographer --help`: exit 0. `git diff --check db2159b d56ad31`: clean. |
