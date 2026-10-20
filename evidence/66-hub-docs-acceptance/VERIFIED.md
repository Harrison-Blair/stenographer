# VERIFIED — 66-hub-docs-acceptance

Independent re-run on commit `cd1cf71`, from the worktree root. Project
environment: `/home/penguin/source/stenographer/.venv` with `PYTHONPATH=src`
(the import resolved to this worktree's `src/stenographer`).

| Item | Result | Observation |
| --- | --- | --- |
| V1 Hub documentation coverage | pass | `docs/hub.md`, README, `docs/live.md`, `site/index.html`, and `CHANGELOG.md` Unreleased cover the six sections, their keys, lifecycle, quit confirmation, Files formats (M4A and AAC need system `ffmpeg`), fixed speaker count, shared ASR default `deepdml/faster-whisper-large-v3-turbo-ct2` with an explicit `asr.model` kept, and the task 58 limit. Spot checks against code match: `HubApp.BINDINGS` and `QuitConfirm.BINDINGS` (`cli/hub/app.py`, `cli/hub/dialogs.py`), relabel constants 0.20 / 2.0 s / 15.0 s / 30.0 s / 2/3 (`lib/live/relabel.py`), the default model (`lib/config/models.py`), `STENOGRAPHER_CONFIG`, `setup --default`, and `model download --live`. |
| V1 Real-machine acceptance plan | pass | `acceptance.md` has a step with an expected result for each of these: open hub, record with space, switch sections while recording, split view, quit confirmation, Files on WAV/MP3/M4A with a fixed-count job, re-diarize a long saved session, Config save with backup, Setup and Doctor, and quit while start or save is finishing (task 103). It contains no transcript text or audio. |
| V1 Git and Hatch allowlists | pass | The commit adds `!/docs/hub.md` to both `.gitignore` and the `pyproject.toml` exclude list. The other differences between the two lists existed before this commit (the `.hive` rules and the generic tool excludes). |
| V1 Changelog validation | pass | `scripts/release_notes.py check 0.14.0 CHANGELOG.md` printed `release note found: v0.14.0 (2026-10-19)`, exit 0. |
| V1 Pages site | pass | Built the site in the scratchpad with the `pages.yml` steps (site copy, icon, fonts, tag substitution). `scripts/check_site.sh` exit 0. The temporary site was removed. |
| V1 Source and binary distributions | pass | `python -m build` built the sdist, then a wheel from that sdist. `scripts/verify_distributions.py` exit 0. The sdist contains `docs/hub.md` (1 match). Neither archive contains `.hive/` (0 matches each). The build output was removed. |
| V2 `ruff check .` | pass | `All checks passed!`, exit 0. |
| V2 `ruff format --check .` | pass | `649 files already formatted`, exit 0. |
| V2 `pytest -m "not integration"` | pass | 2643 passed, 2 skipped (public audio fixtures absent), 6 deselected, exit 0. |
| V2 `stenographer --help` | pass | Exit 0. |

No microphone, system recording, live command, model download, integration
test, or real-machine acceptance check ran. The real-machine steps in
`acceptance.md` are for the user.
