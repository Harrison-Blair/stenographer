# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent's output guard: real cleanup passes, changed meaning does not.

The dictations below are rambly agent requests. The rejected candidates are
edits that read well but change what the speaker authorized, negated, hedged,
asked, or chose; the accepted ones are the cleanups the Agent prompt asks for.
"""

from __future__ import annotations

import pytest

from stenographer.lib.refine.errors import RefineRejectedError
from stenographer.lib.refine.response import agent_guard

COUNT_LIST = (
    "Okay so a couple things. I think the thing is the config loader is kind of slow and you "
    "know it reads the file twice. And also the error message for a missing key is like really "
    "unhelpful. And then also the tests for load_config don't cover the empty file case. So "
    "yeah just investigate those three things and don't fix anything yet."
)
UNCUED_LIST = (
    "So I want to I want to add logging to the refine stage like the model name the latency and "
    "the word count and the rejection reason if there is one but not the transcript text "
    "obviously."
)
PLAN_ONLY = (
    "Um can you look at the hotkey module and just make a plan for how we'd support a second "
    "binding. Only plan it. Don't write any code. I mean we might end up not doing it at all you "
    "know."
)
HEDGED_CHOICE = (
    "For the benchmark maybe use gemma4:12b no wait maybe use qwen3:8b instead because it's "
    "already pulled and I think probably keep the temperature at 0."
)
FLAGS_PATHS = (
    'Run the tests with .venv/bin/pytest -m "not integration" and then also run ruff check with '
    "--fix off like don't pass --fix just report what it finds in the tests/unit directory."
)
QUESTION = (
    "Okay so quick question. Why does the daemon um why does the daemon take like 3 seconds to "
    "start on this machine is it the model load or is it something else?"
)
IDENTIFIERS = (
    "Rename OllamaRefiner to LocalRefiner no actually keep OllamaRefiner and just rename the "
    "method refined_text to guarded_text. And update the callers in cli/daemon."
)
VERSIONS = (
    "So the release notes say 0.13.2 but the pyproject says 0.13.1 and I think the tag is "
    "v0.13.2 so you know just figure out which one is wrong. Don't bump anything."
)
QUOTED = (
    'The error says "output changed dictated wording or order" and I want I want the log line to '
    "keep that exact string. Like don't reword it at all."
)
JUST_INVESTIGATE = (
    "I think the thing is the overlay flickers when the aura starts. It might be the timer or it "
    "might be the repaint. Just investigate it for now and um explain what you find. Don't touch "
    "overlay/platform at all."
)
WAIT = (
    "So wait for the integration run to finish before you do anything else and then if it's "
    "green you can merge dev into main but if it's not green don't merge and just tell me which "
    "tests failed."
)
NEVER = (
    "Add a retry to the update check but never retry more than 2 times and do it without "
    "blocking the hotkey thread. We no longer need the old backoff constant so you can delete "
    "UPDATE_BACKOFF."
)
VALIDATE = (
    "Um so I pushed a fix for the paste release guard. Can you validate it like actually run "
    "through the scenario where RCtrl is held and see if the paste waits. You know don't change "
    "the code just validate."
)
EXPLICIT_TOOL = (
    "Use ripgrep not grep for this. There are two things I need. Find every place we call "
    "subprocess.run and find every place we read os.environ directly."
)
EXPLAIN_HEDGE = (
    "Can you explain how num_predict_for works. Like I think it's possibly too low for long "
    "dictations perhaps. Just explain it I'm not asking you to change NUM_PREDICT_MAX."
)
LONG_RAMBLE = (
    "Alright so I've been thinking about this and there are like four things I want for the "
    "settings window. The first one is a toggle for refine. The second one is a dropdown for the "
    "model. The third one is I guess a slider for min words which defaults to 10 no wait "
    "defaults to 12. And the fourth one is kind of a reset button. But you know only plan this "
    "don't build it I want to see the plan first."
)
LONG_RAMBLE_BULLETED = (
    "I've been thinking about this and there are four things I want for the settings window:\n"
    "- A toggle for refine.\n- A dropdown for the model.\n- I guess a slider for min words, "
    "which defaults to 12.\n- A reset button.\n\nOnly plan this; don't build it. I want to see "
    "the plan first."
)
RUNON_MIXED = (
    "Okay so the first thing is the README header is out of date and you can fix that. And then "
    "the other thing which is kind of separate is the Windows build. Don't change the Windows "
    "build. I just want you to explain why packaging/windows.spec pulls in numpy at all."
)


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        pytest.param(
            COUNT_LIST,
            "A couple things: the config loader is slow and reads the file twice; the error "
            "message for a missing key is unhelpful; the tests for load_config don't cover the "
            "empty file case. Don't just investigate those three things yet, fix them.",
            id="negation-moved-to-another-verb",
        ),
        pytest.param(
            QUESTION,
            "The daemon takes 3 seconds to start on this machine because of the model load, not "
            "something else.",
            id="question-answered",
        ),
        pytest.param(
            QUESTION,
            "Why does the daemon take 3 seconds to start on this machine. It is the model load.",
            id="question-turned-into-statement",
        ),
        pytest.param(
            QUESTION,
            "Quick question. The daemon takes like 3 seconds to start on this machine. It is the "
            "model load or it is something else.",
            id="question-answered-keeping-every-word",
        ),
        pytest.param(
            EXPLICIT_TOOL,
            "Use grep not ripgrep for this. There are two things I need: find every place we call "
            "subprocess.run and find every place we read os.environ directly.",
            id="lowercase-tool-swapped",
        ),
        pytest.param(
            PLAN_ONLY,
            "Can you look at the hotkey module and just make a plan for how we'd support a second "
            "binding, then only write the code once it's planned? Don't wait. We might end up not "
            "doing it at all.",
            id="plan-escalated-to-write",
        ),
        pytest.param(
            JUST_INVESTIGATE,
            "The overlay flickers when the aura starts. It might be the timer or it might be the "
            "repaint. Just investigate it for now, explain what you find, and refactor the timer. "
            "Don't touch overlay/platform at all.",
            id="added-refactor",
        ),
        pytest.param(
            EXPLAIN_HEDGE,
            "Can you explain how num_predict_for works? I think it's possibly too low for long "
            "dictations, perhaps. Just explain it and update the docs. I'm not asking you to "
            "change NUM_PREDICT_MAX.",
            id="added-update",
        ),
        pytest.param(
            VERSIONS,
            "The release notes say 0.13.2, but the pyproject says 0.13.1. I think the tag is "
            "v0.13.2. Just figure out which one is wrong and push the tag. Don't bump anything.",
            id="added-push",
        ),
        pytest.param(
            LONG_RAMBLE,
            "There are four things I want for the settings window: a toggle for refine and a "
            "slider for min words, which defaults to 12. Only plan this, don't build it. I want "
            "to see the plan first.",
            id="dropped-two-of-four-list-items",
        ),
        pytest.param(
            "Add caching to fetch_page with no network access in the tests and only update the "
            "tests.",
            "Add caching to fetch_page with network access in the tests and only update the tests.",
            id="bare-no-dropped",
        ),
        pytest.param(
            "Investigate why the overlay flickers and touch nothing in the overlay package.",
            "Investigate why the overlay flickers and touch everything in the overlay package.",
            id="nothing-dropped",
        ),
        pytest.param(
            "We can keep the old parser or the new one but neither nor none of the flags should "
            "change.",
            "We can keep the old parser or the new one but all of the flags should change.",
            id="nor-none-dropped",
        ),
        pytest.param(
            LONG_RAMBLE,
            "I've been thinking about this and there are four things I want for the settings "
            "window:\n- A toggle for refine.\n- A dropdown for the model.\n- A slider for min "
            "words, which defaults to 12.\n- A reset button.\n\nOnly plan this, don't build it. I "
            "want to see the plan first.",
            id="i-guess-hedge-dropped",
        ),
        pytest.param(
            VERSIONS,
            "The release notes say 0.13.2, but the pyproject says 0.13.1. The tag is v0.13.2. "
            "Just figure out which one is wrong. Don't bump anything.",
            id="i-think-hedge-dropped",
        ),
        pytest.param(
            JUST_INVESTIGATE,
            "The overlay flickers when the aura starts. It is the timer or the repaint. Just "
            "investigate it for now and explain what you find. Don't touch overlay/platform at "
            "all.",
            id="might-hedge-dropped",
        ),
        pytest.param(
            COUNT_LIST,
            "A couple things:\n- The config loader is slow and reads the file twice.\n- The "
            "error message for a missing key is really unhelpful.\n- The tests for load_config "
            "don't cover the empty file case.\n\nInvestigate those three things and don't fix "
            "anything yet.",
            id="scope-just-dropped",
        ),
        pytest.param(
            PLAN_ONLY,
            "Can you look at the hotkey module and just make a plan for how we'd support a second "
            "binding? Don't write any code. We might end up not doing it at all.",
            id="only-plan-dropped",
        ),
        pytest.param(
            "Keep OllamaRefiner exactly as it is for now, no other renames anywhere in the "
            "refine package.",
            "Keep it exactly as it is for now, no other renames anywhere in the refine package.",
            id="protected-token-dropped-before-no",
        ),
        pytest.param(
            "The bug is in OllamaRefiner actually so look there only and report what you find "
            "in the code.",
            "The bug is somewhere else actually so look there only and report what you find in "
            "the code.",
            id="protected-token-dropped-before-actually",
        ),
        pytest.param(
            WAIT,
            "Wait for the integration run to finish before you do anything else. If it's not "
            "green, merge dev into main; if it's green, don't merge and just tell me which tests "
            "failed.",
            id="conditional-flipped",
        ),
        pytest.param(
            IDENTIFIERS,
            "Rename OllamaRefiner to LocalRefiner. Keep refined_text and guarded_text; just "
            "update the callers in cli/daemon.",
            id="self-correction-reversed-identifier",
        ),
        pytest.param(
            HEDGED_CHOICE,
            "For the benchmark, maybe use qwen3:8b no wait maybe use gemma4:12b because it's "
            "already pulled, and probably keep the temperature at 0.",
            id="self-correction-reversed-model",
        ),
        pytest.param(
            "It won't matter much either way and it can't hurt to plan the migration first "
            "before we start.",
            "It will matter much either way and it can hurt to plan the migration first before "
            "we start.",
            id="contractions-dropped",
        ),
        pytest.param(
            "Merge dev into main once the integration run is green and then tag the release "
            "please.",
            "Do not merge dev into main once the integration run is green and then tag the "
            "release please.",
            id="negation-added",
        ),
        pytest.param(
            COUNT_LIST,
            "There are a couple of things. I think the config loader is slow because it reads "
            "the file twice.\n\nJust investigate these three things and don't fix anything "
            "yet:\n- The slow config loader.\n- The unhelpful error message for a missing key.\n"
            "- The tests for load_config not covering the empty file case.",
            id="causation-invented",
        ),
        pytest.param(
            COUNT_LIST,
            "There are a couple things.\n- The config loader is kind of slow because it reads the "
            "file twice.\n- The error message for a missing key is really unhelpful.\n- The tests "
            "for load_config don't cover the empty file case.\n\nJust investigate those three "
            "things and don't fix anything yet.",
            id="causation-invented-in-a-bullet",
        ),
        pytest.param(
            "Please review the migration in db/0042_index.py and explain the new index. I can "
            "sign off on it tomorrow morning.",
            "Please review the migration in db/0042_index.py and explain the new index so that I "
            "can sign off on it tomorrow morning.",
            id="causal-so-that-added",
        ),
        pytest.param(
            "Ask Claude to review the parser changes in the lexer module and report back today.",
            "Ask to review the parser changes in the lexer module and report back today.",
            id="name-dropped",
        ),
        pytest.param(
            "Um so I pushed a fix for the paste release guard last night. Validate it only.",
            "I pushed a fix for the paste release guard last night. Fix it again and validate it "
            "only.",
            id="noun-fix-turned-into-a-verb",
        ),
        pytest.param(
            QUESTION,
            "Quick question. Why does the daemon take 3 seconds to start on this machine? It's the "
            "model load rather than something else.",
            id="answer-appended-after-kept-question",
        ),
        pytest.param(
            EXPLAIN_HEDGE,
            "Can you explain how num_predict_for works? It scales with the input length. I think "
            "it's possibly too low for long dictations perhaps. Just explain it; I'm not asking "
            "you to change NUM_PREDICT_MAX.",
            id="explanation-inserted",
        ),
        pytest.param(
            "Use ripgrep for the search and pipe the output through jq before you summarize it.",
            "Use grep for the search and pipe the output through jq before you summarize it.",
            id="lowercase-tool-swapped-without-contrast",
        ),
        pytest.param(
            "Keep the variable foo unchanged in the parser module and only rename the helper "
            "functions.",
            "Keep the variable bar unchanged in the parser module and only rename the helper "
            "functions.",
            id="lowercase-identifier-swapped",
        ),
        pytest.param(
            "Claude should review the parser changes in the lexer module today and report back.",
            "Gemini should review the parser changes in the lexer module today and report back.",
            id="sentence-start-name-swapped",
        ),
        pytest.param(
            "The nightly backup took 40 minutes last night. Look at the logs and tell me what "
            "happened.",
            "The nightly backup took 40 minutes last night. Look at the logs and tell me what "
            "happened. The disk was full.",
            id="invented-sentence",
        ),
        pytest.param(
            PLAN_ONLY,
            "Can you look at the hotkey module and just make a plan for how we'd support a second "
            "binding, then write the code once it's planned? Only plan it. Don't write any code. "
            "We might end up not doing it at all.",
            id="negated-verb-also-authorized",
        ),
        pytest.param(
            PLAN_ONLY,
            "Can you look at the hotkey module and just make a plan for how we'd support a second "
            "binding? Only plan it, then write it. Don't write any code. We might end up not "
            "doing it at all.",
            id="negated-verb-authorized-in-place",
        ),
        pytest.param(
            "Check the parser tests, the lexer tests, and the parser docs before the release.",
            "Check the parser tests and the lexer tests before the release.",
            id="list-item-with-repeated-words-dropped",
        ),
        pytest.param(
            LONG_RAMBLE,
            "I've been thinking about this and there are four things I want for the settings "
            "window:\n- A toggle for refine.\n- I guess a slider for min words, which defaults to "
            "12.\n- A reset button.\n\nOnly plan this; don't build it. I want to see the plan "
            "first.",
            id="one-bullet-dropped",
        ),
        pytest.param(
            "Maybe change staging, but preserve production and report back when you are done.",
            "Maybe change production, but preserve staging and report back when you are done.",
            id="objects-swapped",
        ),
        pytest.param(
            "Deploy the new build to staging tonight and run the smoke tests there, but "
            "production must not be touched until I sign off tomorrow.",
            "Deploy the new build to production tonight and run the smoke tests there, but "
            "staging must not be touched until I sign off tomorrow.",
            id="objects-swapped-across-clauses",
        ),
        pytest.param(
            "The parser must stay as it is and the lexer should not change at all in this pass.",
            "The lexer must stay as it is and the parser should not change at all in this pass.",
            id="subjects-swapped",
        ),
        pytest.param(
            "There are three things do not change staging and production and review the logs.",
            "There are three things:\n- do not change staging\n- production\n- review the logs",
            id="bullet-split-out-of-a-negation",
        ),
        pytest.param(
            "There are three things. Don't change the config loader or the CLI parser, review the "
            "logs, and explain the flaky test.",
            "There are three things:\n- Don't change the config loader.\n- The CLI parser.\n- "
            "Review the logs.\n- Explain the flaky test.",
            id="bullet-split-out-of-a-negation-after-or",
        ),
        pytest.param(
            "There are three things. Don't change the config loader or the CLI parser, review the "
            "logs, and explain the flaky test.",
            "There are three things. Don't change the config loader. The CLI parser, review the "
            "logs, and explain the flaky test.",
            id="sentence-split-out-of-a-negation",
        ),
        pytest.param(
            "Don't touch the aura timer module or the repaint path code, and review the logs.",
            "Don't touch the aura timer module.\n- The repaint path code.\n- Review the logs.",
            id="bullet-split-five-words-after-a-negation",
        ),
        pytest.param(
            LONG_RAMBLE,
            LONG_RAMBLE_BULLETED.replace("\n- A reset button.", ""),
            id="last-bullet-dropped",
        ),
        pytest.param(
            LONG_RAMBLE,
            LONG_RAMBLE_BULLETED.replace("\n- A toggle for refine.", ""),
            id="first-bullet-dropped",
        ),
        pytest.param(
            LONG_RAMBLE,
            LONG_RAMBLE_BULLETED.replace("- ", "* ").replace("* A dropdown for the model.\n", ""),
            id="star-bullet-dropped",
        ),
        pytest.param(
            "For the search in the tests directory use grep no wait use ripgrep and then summarize "
            "the matches for me.",
            "For the search in the tests directory, use grep and then summarize the matches for "
            "me.",
            id="lowercase-self-correction-reversed",
        ),
        pytest.param(
            "Delete one of the old backups in the archive folder on the build server.",
            "Delete all of the old backups in the archive folder on the build server.",
            id="quantifier-widened",
        ),
        pytest.param(
            "Update the tests for load_config and tell me when it's done.",
            "Update all the tests for load_config and tell me when it's done.",
            id="quantifier-added",
        ),
        pytest.param(
            "Review the migration today and we can merge it after the release.",
            "Review the migration today and we can merge it now, after the release.",
            id="timing-word-added",
        ),
        pytest.param(
            "You could rename the helper if you want but it's your call really.",
            "You should rename the helper if you want, but it's your call.",
            id="modal-strengthened",
        ),
        pytest.param(
            "Keep the release note short and mention the paste fix only.",
            "Keep the release noted short and mention the paste fix only.",
            id="stem-does-not-collide-with-a-negation",
        ),
        pytest.param(
            "Fix the typo in the README, and for the parser bug just investigate and explain what "
            "you find.",
            "Fix the typo in the README, and for the parser bug just investigate, explain what you "
            "find, and fix it.",
            id="action-attached-to-an-investigation",
        ),
        pytest.param(
            "There are three things. Don't change it or the CLI parser, review the logs, and "
            "explain the flaky test.",
            "There are three things:\n- Don't change it.\n- The CLI parser.\n- Review the logs.\n"
            "- Explain the flaky test.",
            id="split-after-a-pronoun-object",
        ),
        pytest.param(
            "Don't delete the old branches we merged or the tags, just list them.",
            "Don't delete the old branches we merged.\n- The tags.\n- Just list them.",
            id="split-after-a-relative-clause",
        ),
        pytest.param(
            "For the nightly benchmark run use the medium model no wait use the small model since "
            "the box has no GPU and then write the numbers to the report file for me please.",
            "For the nightly benchmark run, use the medium model since the box has no GPU and then "
            "write the numbers to the report file for me.",
            id="head-noun-correction-reversed",
        ),
        pytest.param(
            "Compare the staging logs sorry the production logs against last week and summarize "
            "any new errors you see.",
            "Compare the staging logs against last week and summarize any new errors you see.",
            id="head-noun-correction-reversed-after-sorry",
        ),
        pytest.param(
            "Fix the typo in the README, and for the parser bug just investigate and explain what "
            "you find.",
            "Fix the typo in the README. For the parser bug, just investigate and explain what you "
            "find. Then fix it.",
            id="action-in-the-sentence-after-an-investigation",
        ),
        pytest.param(
            "Fix the typo in the README, and for the parser bug just investigate and explain what "
            "you find.",
            "Fix the typo in the README. For the parser bug, just investigate and explain what you "
            "find. So fix it.",
            id="action-after-so-following-an-investigation",
        ),
        pytest.param(
            "Fix the typo in the README, and for the parser bug just investigate and explain what "
            "you find.",
            "Fix the typo in the README.\n\nFor the parser bug:\n- Just investigate.\n- Explain "
            "what you find.\n- Fix it.",
            id="action-bulleted-under-an-investigation",
        ),
        pytest.param(
            "Fix the typo in the README, and for the parser bug just investigate and tell me what "
            "the root cause of the failure seems to be.",
            "Fix the typo in the README. For the parser bug, just investigate and tell me what the "
            "root cause of the failure seems to be. Fix it.",
            id="action-well-after-an-investigation",
        ),
        pytest.param(
            WAIT,
            "Wait for the integration run to finish before you do anything else, then merge dev "
            "into main. If it's not green, don't merge and just tell me which tests failed.",
            id="condition-dropped",
        ),
        pytest.param(
            JUST_INVESTIGATE,
            "I think the overlay flickers when the aura starts. It might be the timer or it might "
            "be the repaint. Just investigate it and explain what you find. Don't touch "
            "overlay/platform at all.",
            id="for-now-dropped",
        ),
        pytest.param(
            "No retries. Just log the failure and move on to the next file in the import queue.",
            "Just log the failure and move on to the next file in the import queue.",
            id="sentence-initial-no-dropped",
        ),
        pytest.param(
            "Can you explain how num_predict_for works for long dictations and where the ceiling "
            "comes from.",
            "Explain how num_predict_for works for long dictations. The ceiling comes from the "
            "config.",
            id="polite-request-made-imperative-and-answered",
        ),
        pytest.param(
            "Why does the daemon take 3 seconds to start on this machine? Is it the model load?",
            "The daemon takes 3 seconds to start on this machine. It is the model load.",
            id="real-question-made-a-statement",
        ),
        pytest.param(
            QUOTED,
            'The error says "output changed the dictated wording," and I want the log line to keep '
            "that exact string. Don't reword it at all.",
            id="quoted-words-changed-beside-a-moved-comma",
        ),
        pytest.param(
            "Can we merge the paste guard branch into dev today or is it too risky?",
            "Merge the paste guard branch into dev today.",
            id="can-we-question-made-a-command",
        ),
        pytest.param(
            "Can we merge the paste guard branch into dev today before the release goes out?",
            "Merge the paste guard branch into dev today before the release goes out.",
            id="can-we-question-made-a-command-without-a-clause",
        ),
        pytest.param(
            "Would you say the cache layer in the export pipeline is the main problem here?",
            "The cache layer in the export pipeline is the main problem here.",
            id="opinion-question-made-a-claim",
        ),
        pytest.param(
            "No I/O in the hot path of the refine guard, keep it pure and review the helpers.",
            "I/O in the hot path of the refine guard, keep it pure and review the helpers.",
            id="no-before-a-slashed-word-dropped",
        ),
        pytest.param(
            "No so-called quick fixes in the guard this time, review the design first.",
            "So-called quick fixes in the guard this time, review the design first.",
            id="no-before-a-hyphenated-word-dropped",
        ),
        pytest.param(
            "Use the old retry logic sorry the new retry logic in the update check and explain the "
            "backoff.",
            "Use the old retry logic in the update check and explain the backoff.",
            id="two-word-head-correction-reversed",
        ),
        pytest.param(
            LONG_RAMBLE,
            LONG_RAMBLE_BULLETED.replace("- ", "\u2022 ").replace(
                "\u2022 A dropdown for the model.\n", ""
            ),
            id="round-bullet-dropped",
        ),
    ],
)
def test_agent_guard_rejects_edits_that_change_meaning(original, candidate):
    with pytest.raises(RefineRejectedError):
        agent_guard(original, candidate)


@pytest.mark.parametrize(
    ("original", "candidate"),
    [
        pytest.param(
            "So um don't don't fix it yet just investigate why the cache keeps growing on the "
            "build machine.",
            "Don\u2019t fix it yet; just investigate why the cache keeps growing on the build "
            "machine.",
            id="stammered-negation-collapsed",
        ),
        pytest.param(
            "Commit this on dev with a conventional commit message but don't push.",
            "Commit this on dev with a conventional commit message, but do not push.",
            id="do-not-spelled-out",
        ),
        pytest.param(
            "Um so I pushed a fix for the paste release guard last night. Validate it only.",
            "I pushed a fix for the paste release guard last night. Validate it only.",
            id="fix-as-a-noun",
        ),
        pytest.param(
            COUNT_LIST,
            "There are a couple things.\n- The config loader is kind of slow and reads the file "
            "twice.\n- The error message for a missing key is really unhelpful.\n- The tests for "
            "load_config don't cover the empty file case.\n\nJust investigate those three things "
            "and don't fix anything yet.",
            id="count-list-bulleted",
        ),
        pytest.param(
            UNCUED_LIST,
            "I want to add logging to the refine stage:\n- the model name\n- the latency\n- the "
            "word count\n- the rejection reason, if there is one.\n\nNot the transcript text, "
            "obviously.",
            id="uncued-list-bulleted",
        ),
        pytest.param(
            PLAN_ONLY,
            "Can you look at the hotkey module and just make a plan for how we'd support a second "
            "binding? Only plan it. Don't write any code. We might end up not doing it at all.",
            id="plan-only",
        ),
        pytest.param(
            HEDGED_CHOICE,
            "For the benchmark, maybe use qwen3:8b instead because it's already pulled. Probably "
            "keep the temperature at 0.",
            id="model-self-correction",
        ),
        pytest.param(
            FLAGS_PATHS,
            'Run the tests with .venv/bin/pytest -m "not integration".\n\nRun ruff check with '
            "--fix off; don't pass --fix, just report what it finds in the tests/unit directory.",
            id="flags-and-paths",
        ),
        pytest.param(
            QUESTION,
            "Why does the daemon take like 3 seconds to start on this machine? Is it the model "
            "load or is it something else?",
            id="question-kept",
        ),
        pytest.param(
            IDENTIFIERS,
            "Keep OllamaRefiner and just rename the method refined_text to guarded_text. Update "
            "the callers in cli/daemon.",
            id="identifier-self-correction",
        ),
        pytest.param(
            IDENTIFIERS,
            "Rename OllamaRefiner to LocalRefiner. Actually, keep OllamaRefiner and just rename "
            "the method refined_text to guarded_text. And update the callers in cli/daemon.",
            id="identifier-self-correction-left-visible",
        ),
        pytest.param(
            VERSIONS,
            "The release notes say 0.13.2, but the pyproject says 0.13.1. I think the tag is "
            "v0.13.2. Just figure out which one is wrong. Don't bump anything.",
            id="versions",
        ),
        pytest.param(
            JUST_INVESTIGATE,
            "I think the overlay flickers when the aura starts. It might be the timer or it might "
            "be the repaint. Just investigate it for now and explain what you find. Don't touch "
            "overlay/platform at all.",
            id="just-investigate",
        ),
        pytest.param(
            WAIT,
            "Wait for the integration run to finish before you do anything else. If it's green, "
            "you can merge dev into main, but if it's not green, don't merge and just tell me "
            "which tests failed.",
            id="conditional-kept",
        ),
        pytest.param(
            RUNON_MIXED,
            "The first thing is the README header is out of date and you can fix that.\n\nThe "
            "other thing, which is kind of separate, is the Windows build. Don't change the "
            "Windows build. I just want you to explain why packaging/windows.spec pulls in numpy "
            "at all.",
            id="topic-shift-paragraphs",
        ),
        pytest.param(
            NEVER,
            "Add a retry to the update check, but never retry more than 2 times and do it without "
            "blocking the hotkey thread.\n\nWe no longer need the old backoff constant, so you "
            "can delete UPDATE_BACKOFF.",
            id="never-without-no-longer",
        ),
        pytest.param(
            VALIDATE,
            "I pushed a fix for the paste release guard. Can you validate it? Actually run "
            "through the scenario where RCtrl is held and see if the paste waits. Don't change "
            "the code just validate.",
            id="validate-only",
        ),
        pytest.param(
            EXPLICIT_TOOL,
            "Use ripgrep not grep for this. There are two things I need:\n- Find every place we "
            "call subprocess.run.\n- Find every place we read os.environ directly.",
            id="tool-choice-with-count-list",
        ),
        pytest.param(
            EXPLICIT_TOOL,
            "Use ripgrep not grep for this. I need two things.\n- Find every place we call "
            "subprocess.run.\n- Find every place we read os.environ directly.",
            id="sentence-after-a-negation-reworded",
        ),
        pytest.param(
            EXPLAIN_HEDGE,
            "Can you explain how num_predict_for works? I think it's possibly too low for long "
            "dictations perhaps. Just explain it; I'm not asking you to change NUM_PREDICT_MAX.",
            id="explain-with-hedges",
        ),
        pytest.param(
            LONG_RAMBLE,
            "I've been thinking about this and there are four things I want for the settings "
            "window:\n- A toggle for refine.\n- A dropdown for the model.\n- I guess a slider for "
            "min words, which defaults to 12.\n- A reset button.\n\nOnly plan this; don't build "
            "it. I want to see the plan first.",
            id="long-ramble-with-numeral-correction",
        ),
        pytest.param(
            "So for the settings window the refine toggle I think should go at the top and the "
            "model dropdown right under it.",
            "For the settings window, I think the refine toggle should go at the top and the model "
            "dropdown right under it.",
            id="hedge-moved-to-the-front",
        ),
        pytest.param(
            "Alright a couple things for the release. Bump the version in pyproject. And also "
            "update the changelog. And then also tag it on dev but don't push the tag.",
            "A couple things for the release:\n- Bump the version in pyproject.\n- Update the "
            "changelog.\n- Tag it on dev, but don't push the tag.",
            id="bullet-ending-in-a-negation",
        ),
        pytest.param(
            "Don't touch the tests. There are three things in the parser. The tests are slow, the "
            "errors are vague, and the docs are stale. Just review them.",
            "Don't touch the tests. There are three things in the parser:\n"
            "- The tests are slow.\n- The errors are vague.\n- The docs are stale.\n\n"
            "Just review them.",
            id="negated-word-starts-a-later-bullet",
        ),
        pytest.param(
            "Can you look at why the setting window takes like two seconds to open on the laptop.",
            "Can you look at why the settings window takes about two seconds to open on the "
            "laptop?",
            id="plural-added",
        ),
        pytest.param(
            "Don't change the loader or the parser. Change the docs, the parser tests are fine.",
            "Don't change the loader or the parser.\nChange the docs.\nThe parser tests are fine.",
            id="split-after-an-unnegated-verb",
        ),
        pytest.param(
            "Don't change the loader or the parser, the parser must not be touched at all this "
            "week.",
            "Don't change the loader or the parser.\nThe parser must not be touched at all this "
            "week.",
            id="split-unit-with-its-own-negation",
        ),
        pytest.param(
            "Don't change the loader, the parser, or the tray icon. Just review the logs.",
            "Don't change:\n- the loader\n- the parser\n- the tray icon\n\nJust review the logs.",
            id="negated-list-bulleted-under-its-lead-in",
        ),
        pytest.param(
            "Don't fix it and just ship the release notes today and then tell me when it's out.",
            "Don't fix it.\nJust ship the release notes today and then tell me when it's out.",
            id="clause-after-a-pronoun-object",
        ),
        pytest.param(
            "Use the medium model no wait use the small model for the benchmark and review the "
            "results.",
            "Use the small model for the benchmark and review the results.",
            id="head-noun-correction-applied",
        ),
        pytest.param(
            "Don't merge the branch I want you to review the diff first and tell me what looks "
            "off.",
            "Don't merge the branch. I want you to review the diff first and tell me what looks "
            "off.",
            id="run-on-split-before-i",
        ),
        pytest.param(
            "Don't touch the overlay code we need it for the demo tomorrow so just review the "
            "daemon logs.",
            "Don't touch the overlay code; we need it for the demo tomorrow, so just review the "
            "daemon logs.",
            id="run-on-split-before-we-at-a-semicolon",
        ),
        pytest.param(
            "Don't touch the overlay code we need it for the demo tomorrow so just review the "
            "daemon logs.",
            "Don't touch the overlay code. We need it for the demo tomorrow, so just review the "
            "daemon logs.",
            id="run-on-split-before-we",
        ),
        pytest.param(
            "Don't commit the migration you can review it and tell me if the index looks right.",
            "Don't commit the migration. You can review it and tell me if the index looks right.",
            id="run-on-split-before-you",
        ),
        pytest.param(
            "Use the old retry logic sorry the new retry logic in the update check and explain the "
            "backoff.",
            "Use the new retry logic in the update check and explain the backoff.",
            id="two-word-head-correction-applied",
        ),
        pytest.param(
            "Okay so investigate the startup crash you know like whatever. And then fix the typo "
            "in the README as well.",
            "Investigate the startup crash. Then fix the typo in the README as well.",
            id="filler-dropped-between-investigation-and-action",
        ),
        pytest.param(
            "Explain why the daemon is slow it's kind of a mystery to me honestly. Then commit the "
            "docs change on dev.",
            "Explain why the daemon is slow; it's a mystery to me. Then commit the docs change on "
            "dev.",
            id="aside-dropped-between-explanation-and-action",
        ),
        pytest.param(
            "Fix the lint, and review the parser changes in the tokenizer module and explain the "
            "naming choices for the error classes, the helper functions, the retry wrapper, the "
            "logging setup, and the cache layer in the nightly export pipeline overall.",
            "Review the parser changes in the tokenizer module and explain the naming choices for "
            "the error classes, the helper functions, the retry wrapper, the logging setup, and "
            "the cache layer in the nightly export pipeline overall. Fix the lint.",
            id="action-moved-far-after-an-investigation",
        ),
        pytest.param(
            "Um can you like look at the logs for the backup job and tell me what happened.",
            "Look at the logs for the backup job and tell me what happened.",
            id="polite-request-made-imperative",
        ),
        pytest.param(
            QUOTED,
            'The error says "output changed dictated wording or order," and I want the log line '
            "to keep that exact string. Don't reword it at all.",
            id="comma-moved-inside-a-closing-quote",
        ),
        pytest.param(
            "No that's fine um go ahead and review the patch for the overlay.",
            "That's fine. Go ahead and review the patch for the overlay.",
            id="interjection-no-dropped",
        ),
        pytest.param(
            "Yeah no so the parser is fine I just want you to review the lexer.",
            "The parser is fine. I just want you to review the lexer.",
            id="yeah-no-dropped",
        ),
        pytest.param(
            "Explain how the refine guard decides to reject something I don't really get it. Oh "
            "and the tray icon is blurry fix that. And bump nothing.",
            "Explain how the refine guard decides to reject something; I don't really get it. "
            "Also, the tray icon is blurry, fix that. And bump nothing.",
            id="also-added",
        ),
        pytest.param(
            "So the test for the paste guard is failing on CI but passing locally and I want "
            "you to explain why before we do anything.",
            "The test for the paste guard fails on CI but passes locally. I want you to explain "
            "why before we do anything.",
            id="tense-changed",
        ),
        pytest.param(
            "Fix all three of the flaky tests in test_live.py: the paste test, the hotkey test, "
            "and the overlay test.",
            "Fix all three of the flaky tests in test_live.py:\n- Fix the paste test.\n- Fix the "
            "hotkey test.\n- Fix the overlay test.",
            id="action-repeated-per-bullet",
        ),
    ],
)
def test_agent_guard_accepts_cleanup_that_keeps_meaning(original, candidate):
    assert agent_guard(original, candidate) == candidate
