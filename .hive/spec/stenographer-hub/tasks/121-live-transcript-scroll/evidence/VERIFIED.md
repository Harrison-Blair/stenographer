# VERIFIED — task 121-live-transcript-scroll

Verifier: `t121-verifier-2`. Checks ran from the task worktree on 2026-10-22.
No microphone, real audio, model, or integration test was used. Tests used fake
sessions and synthetic transcript lines.

| Item | Result | Observation |
| --- | --- | --- |
| Transcript scroll on hub and standalone | pass | The regression tests cover mouse wheel, line keys, page keys, Home/End, and both hub views. |
| Follow the latest line | pass | Tests check initial bottom position, held position after new lines, and resumed follow at bottom. |
| Hub refresh and section routing | pass | Hub test holds position across the 0.1-second refresh. The Config pilot test passes for Up/Down selection. Full suite passes. |
| Live key hints and docs | pass | Both app hints show the scroll keys. README, `docs/live.md`, `docs/hub.md`, and `site/index.html` list the controls. |
| Test red run | pass | With `update_content` reduced to updating the inner Static and `watch_virtual_size` disabled, both new scroll tests failed at the initial bottom-position assertion (`0` vs max `29` standalone and `32` hub). |
| Test green run | pass | Restored implementation: both regression tests passed (`2 passed in 2.18s`). Config navigation test passed (`1 passed in 0.73s`). |
| Visual check | pass | Fresh screens and boards compared below. No state relies on colour alone. |
| Project gate | pass | Ruff, format, pytest, and CLI help all passed; output is below. |

## Visual check

Fresh Textual captures used fake services at 150×45 for the hub and 100×16 for
standalone. The standalone before capture used the prior hint text in the same
fake-session screen. The approved StenoB and LiveSplit boards were recaptured
with headless Firefox from their approved HTML sources. Fresh screen PNGs are
in this folder as `verified-*.png`.

| Board element | state without colour | Result | Cause or decision |
| --- | --- | --- | --- |
| StenoB Live selection | `▶ Live` | matches | The selected section has a glyph and label. |
| StenoB REC panel | `● REC` | matches | REC and elapsed time remain above the transcript. |
| StenoB MIC and SYSTEM panels | `MIC on`, `SYSTEM on` | matches | Source names and states remain visible with words. |
| StenoB mixed transcript | timestamp, speaker, transcript line | matches | The mixed rows remain in the transcript panel. |
| LiveSplit transcript | `MIC · what you said`, `SYSTEM · everyone else` | matches | Split columns and captions remain in place. |
| Live key hints | `↑/↓`, `PgUp/Dn`, `Home/End` | overridden | Goal `g2-live-scroll`, user chat `c7`, adds these hints. |
| Hub transcript scrollbar | top and bottom positions | overridden | Goal `g2-live-scroll`, user chat `c7`, allows the thin accent scrollbar. |
| Standalone hint row | `↑/↓ line PgUp/Dn page Home/End` | overridden | The approved task adds scroll keys. The before/after captures differ only in the hint row. |

The mixed and split hub captures show the transcript at the bottom and scrolled
up. The scrollbar moves between those positions. The panel layout stays the
same as the boards. The key hints stay legible without colour.

## Gate output

The task worktree has no `.venv`, so `.venv` temporarily linked to the registered
stenographer environment at `/home/penguin/source/stenographer/.venv`. The
commands used `PYTHONPATH=src` for project imports.

```text
.venv/bin/ruff check .
All checks passed!

.venv/bin/ruff format --check .
839 files already formatted

PYTHONPATH=src .venv/bin/pytest -m "not integration"
2772 passed, 1 skipped, 7 deselected in 70.71s

PYTHONPATH=src .venv/bin/stenographer --help
Exit status 0; usage and command list printed.
```

The skipped test needs speaker clips that are absent from `tmp/live_audio`.
