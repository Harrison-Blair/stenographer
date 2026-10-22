# Independent verification: task 54

Verdict: **pass**. Reviewed task branch at `043a7a0` against base `1cf20f2`.
Read the complete feature spec, task brief, worker evidence V1–V8, and task diff.
Re-ran the checks below from the worktree root. No source files were changed.

## Results

| Item | Result | Independent observation |
| --- | --- | --- |
| V1 / requirement 1: attribution | pass | Fetched only the pinned 611-byte NOTICE. Its sha256 is `6bd6d22b4414b3ac97869dd8a97a813d668216ef66b04148ac858b988f8d063d`, matching `bark_pins.py`. The asset starts with these exact bytes. CC BY 4.0 and the specified modification line follow. Silero MIT text and TitaNet NeMo/Apache-2.0 notes are present. |
| V1: packaging | pass | `git check-ignore -v --no-index FIX.md src/stenographer/assets/licenses/*.txt` shows explicit allow rules for all files. Git and Hatch license/FIX path rules are identical. Existing wheel license glob and PyInstaller whole-assets collection cover the files. |
| V2 / requirement 2: README | pass | Speech-model instructions name local int8 conversion, CPU, python3-venv, 10 GiB disk, about 10.2 GiB RAM, and about 2 minutes on the test machine. Third-party models is under License; all five entries have authors, license, and links. |
| V3 / requirement 3: docs | pass | Usage, Live, Hub, Refine, and Building agree with the new backend/config. Removed settings are described as ignored and preserved. The experiments document has one dated history note linking the tracked task 26 report. |
| V3: stale-reference grep | pass | The worker's grep was re-run exactly; no matches outside the permitted experiments history. The bare `model =` search finds only the refine model example. |
| V4 / requirement 4: site | pass | Changed copy uses second person. `scripts/check_site.sh` on a fresh Pages-layout assembly exits 0 with no output. Browser capture is attached as `verified-site.png`. |
| V5 / requirement 5: changelog | pass | Unreleased names the breaking change, every mode, removed keys, prerequisite/download, retained fillers, and removed scripts. The release-note checker accepts a scratch copy with Unreleased renamed to v9.9.9; v0.15.0 also passes. No Unreleased line exceeds 79 columns. |
| V6 / requirement 6: FIX.md | pass | Temporary status, user-only sudo, ensurepip check, reinstall --no-start, resource checks, download, doctor, consent for config/cache removal, cache size/path, and microphone restrictions are present. Service start also requires consent. |
| V7 / requirement 7: commands and facts | pass | Re-ran help for root, model, model download, doctor, setup, live, transcribe, run, devices, sounds, completion, and stats (including delete/reset/export/summary). All exit 0. Flags match the docs. `scripts/reinstall.sh --help` confirms --no-start. Code confirms CPU provider, 10 GiB minimum, Silero download with --asr, two ASR config keys, min_words=10, and setup's conversion offer. |
| V8: ruff check | pass | `.venv/bin/ruff check .`: `All checks passed!` |
| V8: ruff format | pass | `.venv/bin/ruff format --check .`: `824 files already formatted` |
| V8: unit gate | pass | `.venv/bin/pytest -m "not integration"`: 2770 passed, 1 skipped, 7 deselected in 110.57 seconds. Skip: absent public speaker clips. Neither named timing flake failed. |
| V8: help gate | pass | `.venv/bin/stenographer --help` exits 0 and lists the expected commands. |
| V8: site gate | pass | `scripts/check_site.sh SCRATCH/site` exits 0 after the Pages workflow's site/asset copy steps. |

This task adds documentation and attribution only. There is no new executable
feature or regression test for a red/green run. The existing unit gate was re-run;
no test was weakened or skipped by this verification.

## Grep evidence

```sh
grep -rn -i -E 'whisper|cuda|cudnn|compute_type|compute type|beam_size|beam size|hotword|initial_prompt|vad_filter|silence_threshold|ct2|asr\.model|turbo|ctranslate|huggingface_hub' README.md docs site packaging/NATIVE-ACCEPTANCE.md BUILD.md AGENTS.md | grep -v '^docs/transcription-experiments.md'; echo matches=$?
# matches=1 (grep exit 1: no matching lines)
grep -rn '^model = ' README.md docs site
# docs/refine.md:193:model = "qwen3.5:4b"
```

CHANGELOG and FIX.md intentionally describe the migration. Experiments retains
historical settings. The report link target is tracked by Git.

## Site visual check

The brief has no Design section or approved board. Feature-spec decision 13
permits text-only screen changes without an approved board. This task changes
site copy only; no style or layout files changed. Board comparison is therefore
overridden by that decision. Captured the assembled page again with Firefox
headless, a fresh scratch profile, and a 1220x5000 window. Reviewed the rendered
page. All state cards have plain-text names without colour.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| Quick-install prerequisite | python3-venv | overridden | No board; spec decision 13. Copy renders within its section. |
| State cards | Recording, Transcribing, Refining, Delivering, Applied, Loading, Cancelled, Error | overridden | No board; spec decision 13. State words remain in plain HTML text without colour. |
| Transcribing caption | Bark Pro, on your CPU | overridden | No board; spec decision 13. Exact caption checked in pill.js; screenshot captures the initial idle animation state. |
| Local transcription pipeline | Underdog Bark 3.0 Pro | overridden | No board; spec decision 13. CPU/local-build copy is present. |
| Install instructions | python3-venv; model download --asr | overridden | No board; spec decision 13. Resource needs and ignored settings are present. |
| CLI hub description | engine, queue, CPU use | overridden | No board; spec decision 13. Removed controls are no longer advertised. |
| Footer credit | Conway Research; CC BY 4.0 | overridden | No board; spec decision 13. Attribution link is present. |

## Check adjustments and limits

- Bare `scripts/check_site.sh` exits 1 with `usage: check_site.sh DIR`.
  The script requires an assembled-site argument. V4/V8 use that interface;
  verification used the same Pages assembly and argument. No script change
  is needed.
- An initial comparison of every Git/Hatch path rule was too broad: the
  Git-only `.hive/spec` rules intentionally differ. The task's license/FIX
  rules match exactly. This was a verifier check correction.
- The first Firefox attempt required creation of the fresh profile folder;
  subsequent captures succeeded.
- Resource/time figures were checked against the feature authority and task
  evidence, not remeasured with another model download. No sudo, reinstall,
  model conversion/download, microphone access, service start, live recording,
  or integration test was performed. Only the permitted NOTICE was fetched.
- Scratch assembly, profile, changelog copy, and intermediate screenshots were
  removed after the final screenshot was saved in this evidence folder.
