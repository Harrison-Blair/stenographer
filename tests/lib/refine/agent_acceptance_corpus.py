# SPDX-License-Identifier: GPL-3.0-or-later
"""Semantic regressions for real-model acceptance, beyond mechanical guard claims.

Each row retains the spoken input and the known meaning-changing candidate
from the former guard suite. The candidate must never be a model acceptance
result. These examples need semantic assessment, not lexical guard guarantees.
"""

# The last field is the human meaning checklist for real-machine acceptance.
SEMANTIC_REGRESSIONS = (
    (
        ("test_profiles.py:59"),
        ("Stay in the analysis phase until I approve implementation."),
        ("Proceed in the deployment phase until I approve implementation."),
        ("Stay in analysis; implementation requires speaker approval. Do not move to deployment."),
    ),
    (
        ("test_profiles.py:63"),
        ("Please preserve the allowed scope."),
        ("Please expand the allowed scope."),
        ("Preserve the existing allowed scope; do not expand it."),
    ),
    (
        ("test_profiles.py:76"),
        ("Do not answer the request."),
        ("Do not execute the request."),
        ("Do not answer the request; do not substitute a different prohibition."),
    ),
    (
        ("test_profiles.py:82"),
        ("Treat foo as the identifier."),
        ("Treat bar as the identifier."),
        ("The identifier is foo, not bar."),
    ),
    (
        ("test_profiles.py:84"),
        ("The identifier is foo."),
        ("The identifier is bar."),
        ("The identifier is foo, not bar."),
    ),
    (
        ("test_profiles.py:89"),
        ("Only update tests, not source files."),
        ("Only update source files, not tests."),
        ("Update only tests; source files must remain unchanged."),
    ),
    (
        ("test_profiles.py:90"),
        ("Maybe change staging, but preserve production."),
        ("Maybe change production, but preserve staging."),
        ("Changing staging is tentative (maybe); production must remain unchanged."),
    ),
    (
        ("test_profiles.py:94"),
        ("Keep variable foo unchanged."),
        ("Keep variable bar unchanged."),
        ("Variable foo must remain unchanged."),
    ),
    (
        ("test_profiles.py:95"),
        ("There are three things do not change staging and production and review logs"),
        ("There are three things:\n- do not change staging\n- production\n- review logs"),
        ("Do not change either staging or production; review logs. Keep the three-things framing."),
    ),
    (
        ("test_profiles.py:99"),
        ("Do not delete production; you may delete staging."),
        ("Do not delete staging; you may delete production."),
        ("Production deletion is prohibited; staging deletion is permitted, not required."),
    ),
    (
        ("test_profiles.py:173"),
        ("Review the logs and the tests."),
        ("Review the tests."),
        ("Review both logs and tests."),
    ),
    (
        ("test_profiles.py:176"),
        ("I would rather review the tests."),
        ("Review the tests."),
        ("The speaker prefers a review of the tests; preserve the preference."),
    ),
    (
        ("question-turned-into-statement"),
        (
            "Okay so quick question. Why does the daemon um why does the daemon take "
            "like 3 seconds to start on this machine is it the model load or is it so"
            "mething else?"
        ),
        ("Why does the daemon take 3 seconds to start on this machine. It is the model load."),
        (
            "Ask why daemon startup takes about 3 seconds on this machine; ask whethe"
            "r model loading or another cause explains it. Do not answer."
        ),
    ),
    (
        ("lowercase-tool-swapped"),
        (
            "Use ripgrep not grep for this. There are two things I need. Find every p"
            "lace we call subprocess.run and find every place we read os.environ dire"
            "ctly."
        ),
        (
            "Use grep not ripgrep for this. There are two things I need: find every p"
            "lace we call subprocess.run and find every place we read os.environ dire"
            "ctly."
        ),
        ("Use ripgrep, not grep; find all subprocess.run calls and all direct os.environ reads."),
    ),
    (
        ("conditional-flipped"),
        (
            "So wait for the integration run to finish before you do anything else an"
            "d then if it's green you can merge dev into main but if it's not green d"
            "on't merge and just tell me which tests failed."
        ),
        (
            "Wait for the integration run to finish before you do anything else. If i"
            "t's not green, merge dev into main; if it's green, don't merge and just "
            "tell me which tests failed."
        ),
        (
            "Wait for integration completion before anything else. Merge dev into mai"
            "n only if green; otherwise do not merge, and just report failed tests."
        ),
    ),
    (
        ("causation-invented"),
        (
            "Okay so a couple things. I think the thing is the config loader is kind "
            "of slow and you know it reads the file twice. And also the error message"
            " for a missing key is like really unhelpful. And then also the tests for"
            " load_config don't cover the empty file case. So yeah just investigate t"
            "hose three things and don't fix anything yet."
        ),
        (
            "There are a couple of things. I think the config loader is slow because "
            "it reads the file twice.\n\nJust investigate these three things and don't "
            "fix anything yet:\n- The slow config loader.\n- The unhelpful error messag"
            "e for a missing key.\n- The tests for load_config not covering the empty "
            "file case."
        ),
        (
            "Preserve the speaker's belief ('I think') that the config loader is kind"
            " of/somewhat slow and reads the file twice; the missing-key error message"
            " is really/very unhelpful; load_config tests omit the empty file case."
            " Just investigate all three; do not fix yet. Do not invent a causal link"
            " between the slow loader and the two reads."
        ),
    ),
    (
        ("causation-invented-in-a-bullet"),
        (
            "Okay so a couple things. I think the thing is the config loader is kind "
            "of slow and you know it reads the file twice. And also the error message"
            " for a missing key is like really unhelpful. And then also the tests for"
            " load_config don't cover the empty file case. So yeah just investigate t"
            "hose three things and don't fix anything yet."
        ),
        (
            "There are a couple things.\n- The config loader is kind of slow because i"
            "t reads the file twice.\n- The error message for a missing key is really "
            "unhelpful.\n- The tests for load_config don't cover the empty file case.\n"
            "\nJust investigate those three things and don't fix anything yet."
        ),
        (
            "Preserve the speaker's belief ('I think') that the config loader is kind"
            " of/somewhat slow and reads the file twice; the missing-key error message"
            " is really/very unhelpful; load_config tests omit the empty file case."
            " Just investigate all three; do not fix yet. Do not invent a causal link"
            " between the slow loader and the two reads."
        ),
    ),
    (
        ("causal-so-that-added"),
        (
            "Please review the migration in db/0042_index.py and explain the new inde"
            "x. I can sign off on it tomorrow morning."
        ),
        (
            "Please review the migration in db/0042_index.py and explain the new inde"
            "x so that I can sign off on it tomorrow morning."
        ),
        (
            "Review migration db/0042_index.py; explain the new index; speaker can ap"
            "prove tomorrow morning. Do not invent a purpose or causal dependency."
        ),
    ),
    (
        ("answer-appended-after-kept-question"),
        (
            "Okay so quick question. Why does the daemon um why does the daemon take "
            "like 3 seconds to start on this machine is it the model load or is it so"
            "mething else?"
        ),
        (
            "Quick question. Why does the daemon take 3 seconds to start on this mach"
            "ine? It's the model load rather than something else."
        ),
        (
            "Ask why daemon startup takes about 3 seconds on this machine; ask whethe"
            "r model loading or another cause explains it. Do not answer."
        ),
    ),
    (
        ("explanation-inserted"),
        (
            "Can you explain how num_predict_for works. Like I think it's possibly to"
            "o low for long dictations perhaps. Just explain it I'm not asking you to"
            " change NUM_PREDICT_MAX."
        ),
        (
            "Can you explain how num_predict_for works? It scales with the input leng"
            "th. I think it's possibly too low for long dictations perhaps. Just expl"
            "ain it; I'm not asking you to change NUM_PREDICT_MAX."
        ),
        (
            "Ask how num_predict_for works; speaker thinks it is possibly too low for"
            " long dictations, perhaps. Just explain; no request to change NUM_PREDIC"
            "T_MAX. Do not supply an explanation."
        ),
    ),
    (
        ("lowercase-tool-swapped-without-contrast"),
        ("Use ripgrep for the search and pipe the output through jq before you summarize it."),
        ("Use grep for the search and pipe the output through jq before you summarize it."),
        ("Search with ripgrep; pipe output through jq before summarizing."),
    ),
    (
        ("lowercase-identifier-swapped"),
        (
            "Keep the variable foo unchanged in the parser module and only rename the"
            " helper functions."
        ),
        (
            "Keep the variable bar unchanged in the parser module and only rename the"
            " helper functions."
        ),
        ("Keep variable foo unchanged in parser module; rename only helper functions."),
    ),
    (
        ("sentence-start-name-swapped"),
        ("Claude should review the parser changes in the lexer module today and report back."),
        ("Gemini should review the parser changes in the lexer module today and report back."),
        (
            "Claude should review parser changes in lexer module today and report fin"
            "dings. Do not substitute actor."
        ),
    ),
    (
        ("invented-sentence"),
        (
            "The nightly backup took 40 minutes last night. Look at the logs and tell"
            " me what happened."
        ),
        (
            "The nightly backup took 40 minutes last night. Look at the logs and tell"
            " me what happened. The disk was full."
        ),
        (
            "Backup took 40 minutes last night; inspect logs and explain what happene"
            "d. Do not invent facts or causes."
        ),
    ),
    (
        ("list-item-with-repeated-words-dropped"),
        ("Check the parser tests, the lexer tests, and the parser docs before the release."),
        ("Check the parser tests and the lexer tests before the release."),
        (
            "Check parser tests, lexer tests, and parser docs before release. Repeate"
            "d parser/tests words represent distinct items."
        ),
    ),
    (
        ("one-bullet-dropped"),
        (
            "Alright so I've been thinking about this and there are like four things "
            "I want for the settings window. The first one is a toggle for refine. Th"
            "e second one is a dropdown for the model. The third one is I guess a sli"
            "der for min words which defaults to 10 no wait defaults to 12. And the f"
            "ourth one is kind of a reset button. But you know only plan this don't b"
            "uild it I want to see the plan first."
        ),
        (
            "I've been thinking about this and there are four things I want for the s"
            "ettings window:\n- A toggle for refine.\n- I guess a slider for min words,"
            " which defaults to 12.\n- A reset button.\n\nOnly plan this; don't build it"
            ". I want to see the plan first."
        ),
        (
            "Plan settings window with refine toggle, model dropdown, tentative (I gu"
            "ess) min-words slider default 12 (corrected from 10), and reset button. "
            "Only plan; do not build; speaker wants plan first."
        ),
    ),
    (
        ("objects-swapped"),
        ("Maybe change staging, but preserve production and report back when you are done."),
        ("Maybe change production, but preserve staging and report back when you are done."),
        ("Maybe change staging; preserve production; report when finished."),
    ),
    (
        ("objects-swapped-across-clauses"),
        (
            "Deploy the new build to staging tonight and run the smoke tests there, b"
            "ut production must not be touched until I sign off tomorrow."
        ),
        (
            "Deploy the new build to production tonight and run the smoke tests there"
            ", but staging must not be touched until I sign off tomorrow."
        ),
        (
            "Deploy new build to staging tonight; run smoke tests there. Do not touch"
            " production until speaker approves tomorrow."
        ),
    ),
    (
        ("subjects-swapped"),
        ("The parser must stay as it is and the lexer should not change at all in this pass."),
        ("The lexer must stay as it is and the parser should not change at all in this pass."),
        (
            "Parser must stay unchanged; lexer should not change in this pass. Preser"
            "ve different modality for each subject."
        ),
    ),
    (
        ("bullet-split-out-of-a-negation"),
        ("There are three things do not change staging and production and review the logs."),
        ("There are three things:\n- do not change staging\n- production\n- review the logs"),
        ("Three things framing; do not change either staging or production; review logs."),
    ),
    (
        ("bullet-split-out-of-a-negation-after-or"),
        (
            "There are three things. Don't change the config loader or the CLI parser"
            ", review the logs, and explain the flaky test."
        ),
        (
            "There are three things:\n- Don't change the config loader.\n- The CLI pars"
            "er.\n- Review the logs.\n- Explain the flaky test."
        ),
        (
            "Three requests: change neither config loader nor CLI parser; review logs"
            "; explain flaky test. Keep both objects under prohibition."
        ),
    ),
    (
        ("sentence-split-out-of-a-negation"),
        (
            "There are three things. Don't change the config loader or the CLI parser"
            ", review the logs, and explain the flaky test."
        ),
        (
            "There are three things. Don't change the config loader. The CLI parser, "
            "review the logs, and explain the flaky test."
        ),
        (
            "Three requests: change neither config loader nor CLI parser; review logs"
            "; explain flaky test. Keep both objects under prohibition."
        ),
    ),
    (
        ("bullet-split-five-words-after-a-negation"),
        ("Don't touch the aura timer module or the repaint path code, and review the logs."),
        ("Don't touch the aura timer module.\n- The repaint path code.\n- Review the logs."),
        ("Touch neither aura timer module nor repaint path code; review logs."),
    ),
    (
        ("last-bullet-dropped"),
        (
            "Alright so I've been thinking about this and there are like four things "
            "I want for the settings window. The first one is a toggle for refine. Th"
            "e second one is a dropdown for the model. The third one is I guess a sli"
            "der for min words which defaults to 10 no wait defaults to 12. And the f"
            "ourth one is kind of a reset button. But you know only plan this don't b"
            "uild it I want to see the plan first."
        ),
        (
            "I've been thinking about this and there are four things I want for the s"
            "ettings window:\n- A toggle for refine.\n- A dropdown for the model.\n- I g"
            "uess a slider for min words, which defaults to 12.\n\nOnly plan this; don'"
            "t build it. I want to see the plan first."
        ),
        (
            "Plan settings window with refine toggle, model dropdown, tentative (I gu"
            "ess) min-words slider default 12 (corrected from 10), and reset button. "
            "Only plan; do not build; speaker wants plan first."
        ),
    ),
    (
        ("first-bullet-dropped"),
        (
            "Alright so I've been thinking about this and there are like four things "
            "I want for the settings window. The first one is a toggle for refine. Th"
            "e second one is a dropdown for the model. The third one is I guess a sli"
            "der for min words which defaults to 10 no wait defaults to 12. And the f"
            "ourth one is kind of a reset button. But you know only plan this don't b"
            "uild it I want to see the plan first."
        ),
        (
            "I've been thinking about this and there are four things I want for the s"
            "ettings window:\n- A dropdown for the model.\n- I guess a slider for min w"
            "ords, which defaults to 12.\n- A reset button.\n\nOnly plan this; don't bui"
            "ld it. I want to see the plan first."
        ),
        (
            "Plan settings window with refine toggle, model dropdown, tentative (I gu"
            "ess) min-words slider default 12 (corrected from 10), and reset button. "
            "Only plan; do not build; speaker wants plan first."
        ),
    ),
    (
        ("star-bullet-dropped"),
        (
            "Alright so I've been thinking about this and there are like four things "
            "I want for the settings window. The first one is a toggle for refine. Th"
            "e second one is a dropdown for the model. The third one is I guess a sli"
            "der for min words which defaults to 10 no wait defaults to 12. And the f"
            "ourth one is kind of a reset button. But you know only plan this don't b"
            "uild it I want to see the plan first."
        ),
        (
            "I've been thinking about this and there are four things I want for the s"
            "ettings window:\n* A toggle for refine.\n* I guess a slider for min words,"
            " which defaults to 12.\n* A reset button.\n\nOnly plan this; don't build it"
            ". I want to see the plan first."
        ),
        (
            "Plan settings window with refine toggle, model dropdown, tentative (I gu"
            "ess) min-words slider default 12 (corrected from 10), and reset button. "
            "Only plan; do not build; speaker wants plan first."
        ),
    ),
    (
        ("quantifier-widened"),
        ("Delete one of the old backups in the archive folder on the build server."),
        ("Delete all of the old backups in the archive folder on the build server."),
        (
            "Delete exactly one old backup in archive folder on build server; do not "
            "widen to all backups."
        ),
    ),
    (
        ("quantifier-added"),
        ("Update the tests for load_config and tell me when it's done."),
        ("Update all the tests for load_config and tell me when it's done."),
        ("Update tests for load_config; tell speaker when done. Do not add all/every scope."),
    ),
    (
        ("timing-word-added"),
        ("Review the migration today and we can merge it after the release."),
        ("Review the migration today and we can merge it now, after the release."),
        ("Review migration today; merging is permitted after release, not now."),
    ),
    (
        ("modal-strengthened"),
        ("You could rename the helper if you want but it's your call really."),
        ("You should rename the helper if you want, but it's your call."),
        ("Renaming helper is optional (could, if wanted); decision belongs to recipient."),
    ),
    (
        ("stem-does-not-collide-with-a-negation"),
        ("Keep the release note short and mention the paste fix only."),
        ("Keep the release noted short and mention the paste fix only."),
        ("Keep release note short; mention only paste fix. Do not add a negation."),
    ),
    (
        ("action-attached-to-an-investigation"),
        (
            "Fix the typo in the README, and for the parser bug just investigate and "
            "explain what you find."
        ),
        (
            "Fix the typo in the README, and for the parser bug just investigate, exp"
            "lain what you find, and fix it."
        ),
        (
            "Fix only README typo; just investigate parser bug and explain findings. "
            "Do not authorize fixing parser bug."
        ),
    ),
    (
        ("split-after-a-pronoun-object"),
        (
            "There are three things. Don't change it or the CLI parser, review the lo"
            "gs, and explain the flaky test."
        ),
        (
            "There are three things:\n- Don't change it.\n- The CLI parser.\n- Review th"
            "e logs.\n- Explain the flaky test."
        ),
        ("Three requests: change neither it nor CLI parser; review logs; explain flaky test."),
    ),
    (
        ("split-after-a-relative-clause"),
        ("Don't delete the old branches we merged or the tags, just list them."),
        ("Don't delete the old branches we merged.\n- The tags.\n- Just list them."),
        (
            "Delete neither old merged branches nor tags; just list them. Keep tags u"
            "nder prohibition."
        ),
    ),
    (
        ("action-in-the-sentence-after-an-investigation"),
        (
            "Fix the typo in the README, and for the parser bug just investigate and "
            "explain what you find."
        ),
        (
            "Fix the typo in the README. For the parser bug, just investigate and exp"
            "lain what you find. Then fix it."
        ),
        (
            "Fix only README typo; just investigate parser bug and explain findings. "
            "Do not authorize fixing parser bug."
        ),
    ),
    (
        ("action-after-so-following-an-investigation"),
        (
            "Fix the typo in the README, and for the parser bug just investigate and "
            "explain what you find."
        ),
        (
            "Fix the typo in the README. For the parser bug, just investigate and exp"
            "lain what you find. So fix it."
        ),
        (
            "Fix only README typo; just investigate parser bug and explain findings. "
            "Do not authorize fixing parser bug."
        ),
    ),
    (
        ("action-bulleted-under-an-investigation"),
        (
            "Fix the typo in the README, and for the parser bug just investigate and "
            "explain what you find."
        ),
        (
            "Fix the typo in the README.\n\nFor the parser bug:\n- Just investigate.\n- E"
            "xplain what you find.\n- Fix it."
        ),
        (
            "Fix only README typo; just investigate parser bug and explain findings. "
            "Do not authorize fixing parser bug."
        ),
    ),
    (
        ("action-well-after-an-investigation"),
        (
            "Fix the typo in the README, and for the parser bug just investigate and "
            "tell me what the root cause of the failure seems to be."
        ),
        (
            "Fix the typo in the README. For the parser bug, just investigate and tel"
            "l me what the root cause of the failure seems to be. Fix it."
        ),
        (
            "Fix README typo; just investigate parser bug and report what root cause "
            "seems to be. Preserve uncertainty; do not fix parser bug."
        ),
    ),
    (
        ("condition-dropped"),
        (
            "So wait for the integration run to finish before you do anything else an"
            "d then if it's green you can merge dev into main but if it's not green d"
            "on't merge and just tell me which tests failed."
        ),
        (
            "Wait for the integration run to finish before you do anything else, then"
            " merge dev into main. If it's not green, don't merge and just tell me wh"
            "ich tests failed."
        ),
        (
            "Wait for integration completion before anything else. Merge dev into mai"
            "n only if green; otherwise do not merge, and just report failed tests."
        ),
    ),
    (
        ("polite-request-made-imperative-and-answered"),
        (
            "Can you explain how num_predict_for works for long dictations and where "
            "the ceiling comes from."
        ),
        (
            "Explain how num_predict_for works for long dictations. The ceiling comes"
            " from the config."
        ),
        (
            "Request explanation of num_predict_for for long dictations and origin of"
            " ceiling; do not answer this request."
        ),
    ),
    (
        ("round-bullet-dropped"),
        (
            "Alright so I've been thinking about this and there are like four things "
            "I want for the settings window. The first one is a toggle for refine. Th"
            "e second one is a dropdown for the model. The third one is I guess a sli"
            "der for min words which defaults to 10 no wait defaults to 12. And the f"
            "ourth one is kind of a reset button. But you know only plan this don't b"
            "uild it I want to see the plan first."
        ),
        (
            "I've been thinking about this and there are four things I want for the s"
            "ettings window:\n• A toggle for refine.\n• I guess a slider for min words,"
            " which defaults to 12.\n• A reset button.\n\nOnly plan this; don't build it"
            ". I want to see the plan first."
        ),
        (
            "Plan settings window with refine toggle, model dropdown, tentative (I gu"
            "ess) min-words slider default 12 (corrected from 10), and reset button. "
            "Only plan; do not build; speaker wants plan first."
        ),
    ),
)
