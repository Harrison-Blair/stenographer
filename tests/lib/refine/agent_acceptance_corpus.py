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

# Former semantic guard refusals remain real-model acceptance cases.
SEMANTIC_REGRESSIONS += (
    (
        "former-delivery-semantic-fallback",
        "Only investigate private_job.py and do not change it. ",
        "Change private_job.py.",
        "Only investigate private_job.py; changing it is prohibited.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_changed_safety_bearing_content:0",
        "Do not run --force on /tmp/data.",
        "Run --force on /tmp/data.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Do not run --force on /tmp/data.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_changed_safety_bearing_content:1",
        "Maybe review ClientID first.",
        "Review ClientID first.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Maybe review ClientID first.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_changed_safety_bearing_content:2",
        'Use model qwen3.5:4b and quote "dry run".',
        'Use model gemma4:e2b and quote "dry run".',
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        'spoken input: Use model qwen3.5:4b and quote "dry run".',
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_changed_safety_bearing_content:3",
        "Only investigate the bug before implementing it.",
        "Implement the bug fix.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Only investigate the bug before implementing it.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:0",
        "Use the Codex tool for this request.",
        "Use the Gemini tool for this request.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use the Codex tool for this request.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:1",
        "Pick Claude for this task.",
        "Pick Gemini for this task.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Pick Claude for this task.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:2",
        "Use the Visual Studio Code tool for this review.",
        "Use the Gemini CLI tool for this review.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use the Visual Studio Code tool for this review.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:3",
        "Work only within the read-only investigation phase.",
        "Work within the implementation phase.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Work only within the read-only investigation phase.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:4",
        "Do not proceed without explicit authorization from the owner.",
        "Proceed with implicit permission from the owner.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Do not proceed without explicit authorization from the owner.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:5",
        "Maybe review the patch first.",
        "Maybe deploy the patch first.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Maybe review the patch first.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:6",
        "The selected model is Claude Sonnet.",
        "The selected model is Gemini Pro.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: The selected model is Claude Sonnet.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:7",
        "Claude Sonnet is the selected model.",
        "Gemini Pro is the selected model.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Claude Sonnet is the selected model.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:8",
        "Set the model to Claude for this task.",
        "Set the model to Gemini for this task.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Set the model to Claude for this task.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:9",
        "I want Claude as the tool for this task.",
        "I want Gemini as the tool for this task.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I want Claude as the tool for this task.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:10",
        "Set Claude Sonnet as the model.",
        "Set Gemini Pro as the model.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Set Claude Sonnet as the model.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:11",
        "Set the tool to the Visual Studio Code extension.",
        "Set the tool to the Gemini CLI extension.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Set the tool to the Visual Studio Code extension.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:12",
        "Do not deploy no wait review the change.",
        "Do deploy review the change.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Do not deploy no wait review the change.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:13",
        "Only update tests sorry update docs.",
        "Update tests update docs.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Only update tests sorry update docs.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:14",
        "Maybe change staging actually preserve production.",
        "Change staging preserve production.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Maybe change staging actually preserve production.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:15",
        "Do not deploy no wait review the change.",
        "Do review the change.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Do not deploy no wait review the change.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:16",
        "Do not deploy. Review logs actually keep tests and produce a detailed report with "
        "findings.",
        "Keep tests and produce a detailed report with findings.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Do not deploy. Review logs "
        "actually keep tests and produce a detailed report "
        "with findings.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:17",
        "Use Codex for analysis. Draft notes no wait write the report with findings.",
        "Write the report with findings.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use Codex for analysis. Draft notes no wait write the report with findings.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_tool_model_and_boundary_substitutions:18",
        "Only update tests. Deploy the change sorry review the change.",
        "Review the change.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Only update tests. Deploy the change sorry review the change.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_dropped_content_and_changed_tokens:0",
        "Use --dry-run on /tmp/demo.",
        "Use --force on /tmp/other.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use --dry-run on /tmp/demo.",
    ),
    (
        "test_profiles.py:test_agent_guard_rejects_dropped_content_and_changed_tokens:1",
        "I have no permission.",
        "Permission.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I have no permission.",
    ),
    (
        "negation-moved-to-another-verb",
        "Okay so a couple things. I think the thing is the config loader is kind of slow and you "
        "know it reads the file twice. And also the error message for a missing key is like really "
        "unhelpful. And then also the tests for load_config don't cover the empty file case. So "
        "yeah just investigate those three things and don't fix anything yet.",
        "A couple things: the config loader is slow "
        "and reads the file twice; the error message for "
        "a missing key is unhelpful; the tests for load_config don't cover the empty file case. "
        "Don't just investigate those three things yet, fix them.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Okay so a couple things. I think the thing is the config loader is kind of "
        "slow and you know it reads the file twice. "
        "And also the error message for a missing key is "
        "like really unhelpful. And then also the tests for load_config don't cover the empty file "
        "case. So yeah just investigate those three things and don't fix anything yet.",
    ),
    (
        "question-answered",
        "Okay so quick question. Why does the daemon um why does the daemon take like 3 seconds to "
        "start on this machine is it the model load or is it something else?",
        "The daemon takes 3 seconds to start on this machine because of the model load, not "
        "something else.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Okay so quick question. Why "
        "does the daemon um why does the daemon take like "
        "3 seconds to start on this machine is it the model load or is it something else?",
    ),
    (
        "question-answered-keeping-every-word",
        "Okay so quick question. Why does the daemon um why does the daemon take like 3 seconds to "
        "start on this machine is it the model load or is it something else?",
        "Quick question. The daemon takes like 3 seconds to start on this machine. It is the model "
        "load or it is something else.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Okay so quick question. Why "
        "does the daemon um why does the daemon take like "
        "3 seconds to start on this machine is it the model load or is it something else?",
    ),
    (
        "plan-escalated-to-write",
        "Um can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding. Only plan it. Don't write any code. I mean we might end up not doing it at all "
        "you know.",
        "Can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding, then only write the code once it's "
        "planned? Don't wait. We might end up not doing "
        "it at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Um can you look at the hotkey module and just make a plan for how we'd "
        "support a second binding. Only plan it. Don't write any code. I mean we might end up not "
        "doing it at all you know.",
    ),
    (
        "added-refactor",
        "I think the thing is the overlay flickers when the aura starts. It might be the timer or "
        "it might be the repaint. Just investigate it for now and um explain what you find. Don't "
        "touch overlay/platform at all.",
        "The overlay flickers when the aura starts. It might be the timer or it might be the "
        "repaint. Just investigate it for now, "
        "explain what you find, and refactor the timer. Don't "
        "touch overlay/platform at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I think the thing is the overlay flickers when the aura starts. It might be "
        "the timer or it might be the repaint. Just investigate it for now and um explain what you "
        "find. Don't touch overlay/platform at all.",
    ),
    (
        "added-update",
        "Can you explain how num_predict_for works. Like I think it's possibly too low for long "
        "dictations perhaps. Just explain it I'm not asking you to change NUM_PREDICT_MAX.",
        "Can you explain how num_predict_for works? I think it's possibly too low for long "
        "dictations, perhaps. Just explain it and update the docs. I'm not asking you to change "
        "NUM_PREDICT_MAX.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Can you explain how num_predict_for works. Like I think it's possibly too "
        "low for long dictations perhaps. Just explain it I'm not asking you to change "
        "NUM_PREDICT_MAX.",
    ),
    (
        "added-push",
        "So the release notes say 0.13.2 but the pyproject says 0.13.1 and I think the tag is "
        "v0.13.2 so you know just figure out which one is wrong. Don't bump anything.",
        "The release notes say 0.13.2, but the pyproject says 0.13.1. I think the tag is v0.13.2. "
        "Just figure out which one is wrong and push the tag. Don't bump anything.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: So the release notes say 0.13.2 but the pyproject says 0.13.1 and I think "
        "the tag is v0.13.2 so you know just figure out which one is wrong. Don't bump anything.",
    ),
    (
        "dropped-two-of-four-list-items",
        "Alright so I've been thinking about this and there are like four things I want for the "
        "settings window. The first one is a toggle for refine. The second one is a dropdown for "
        "the model. The third one is I guess a slider for min words which defaults to 10 no wait "
        "defaults to 12. And the fourth one is kind of a reset button. But you know only plan this "
        "don't build it I want to see the plan first.",
        "There are four things I want for the "
        "settings window: a toggle for refine and a slider for "
        "min words, which defaults to 12. Only plan this, don't build it. I want to see the plan "
        "first.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Alright so I've been thinking about this and there are like four things I "
        "want for the settings window. The first one is a toggle for refine. The second one is a "
        "dropdown for the model. The third one is I guess a slider for min words which defaults to "
        "10 no wait defaults to 12. And the fourth "
        "one is kind of a reset button. But you know only "
        "plan this don't build it I want to see the plan first.",
    ),
    (
        "bare-no-dropped",
        "Add caching to fetch_page with no network access in the tests and only update the tests.",
        "Add caching to fetch_page with network access in the tests and only update the tests.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Add caching to fetch_page with no network access in the tests and only "
        "update the tests.",
    ),
    (
        "nothing-dropped",
        "Investigate why the overlay flickers and touch nothing in the overlay package.",
        "Investigate why the overlay flickers and touch everything in the overlay package.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Investigate why the overlay flickers and touch nothing in the overlay "
        "package.",
    ),
    (
        "nor-none-dropped",
        "We can keep the old parser or the new one "
        "but neither nor none of the flags should change.",
        "We can keep the old parser or the new one but all of the flags should change.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: We can keep the old parser or the new one but neither nor none of the flags "
        "should change.",
    ),
    (
        "i-guess-hedge-dropped",
        "Alright so I've been thinking about this and there are like four things I want for the "
        "settings window. The first one is a toggle for refine. The second one is a dropdown for "
        "the model. The third one is I guess a slider for min words which defaults to 10 no wait "
        "defaults to 12. And the fourth one is kind of a reset button. But you know only plan this "
        "don't build it I want to see the plan first.",
        "I've been thinking about this and there are four things I want for the settings window:\n"
        "- A toggle for refine.\n"
        "- A dropdown for the model.\n"
        "- A slider for min words, which defaults to 12.\n"
        "- A reset button.\n"
        "\n"
        "Only plan this, don't build it. I want to see the plan first.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Alright so I've been thinking about this and there are like four things I "
        "want for the settings window. The first one is a toggle for refine. The second one is a "
        "dropdown for the model. The third one is I guess a slider for min words which defaults to "
        "10 no wait defaults to 12. And the fourth "
        "one is kind of a reset button. But you know only "
        "plan this don't build it I want to see the plan first.",
    ),
    (
        "i-think-hedge-dropped",
        "So the release notes say 0.13.2 but the pyproject says 0.13.1 and I think the tag is "
        "v0.13.2 so you know just figure out which one is wrong. Don't bump anything.",
        "The release notes say 0.13.2, but the pyproject says 0.13.1. The tag is v0.13.2. Just "
        "figure out which one is wrong. Don't bump anything.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: So the release notes say 0.13.2 but the pyproject says 0.13.1 and I think "
        "the tag is v0.13.2 so you know just figure out which one is wrong. Don't bump anything.",
    ),
    (
        "might-hedge-dropped",
        "I think the thing is the overlay flickers when the aura starts. It might be the timer or "
        "it might be the repaint. Just investigate it for now and um explain what you find. Don't "
        "touch overlay/platform at all.",
        "The overlay flickers when the aura starts. It is the timer or the repaint. Just "
        "investigate it for now and explain what you find. Don't touch overlay/platform at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I think the thing is the overlay flickers when the aura starts. It might be "
        "the timer or it might be the repaint. Just investigate it for now and um explain what you "
        "find. Don't touch overlay/platform at all.",
    ),
    (
        "scope-just-dropped",
        "Okay so a couple things. I think the thing is the config loader is kind of slow and you "
        "know it reads the file twice. And also the error message for a missing key is like really "
        "unhelpful. And then also the tests for load_config don't cover the empty file case. So "
        "yeah just investigate those three things and don't fix anything yet.",
        "A couple things:\n"
        "- The config loader is slow and reads the file twice.\n"
        "- The error message for a missing key is really unhelpful.\n"
        "- The tests for load_config don't cover the empty file case.\n"
        "\n"
        "Investigate those three things and don't fix anything yet.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Okay so a couple things. I think the thing is the config loader is kind of "
        "slow and you know it reads the file twice. "
        "And also the error message for a missing key is "
        "like really unhelpful. And then also the tests for load_config don't cover the empty file "
        "case. So yeah just investigate those three things and don't fix anything yet.",
    ),
    (
        "only-plan-dropped",
        "Um can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding. Only plan it. Don't write any code. I mean we might end up not doing it at all "
        "you know.",
        "Can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding? Don't write any code. We might end up not doing it at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Um can you look at the hotkey module and just make a plan for how we'd "
        "support a second binding. Only plan it. Don't write any code. I mean we might end up not "
        "doing it at all you know.",
    ),
    (
        "protected-token-dropped-before-no",
        "Keep OllamaRefiner exactly as it is for now, no other renames anywhere in the refine "
        "package.",
        "Keep it exactly as it is for now, no other renames anywhere in the refine package.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Keep OllamaRefiner exactly as it is for now, no other renames anywhere in "
        "the refine package.",
    ),
    (
        "protected-token-dropped-before-actually",
        "The bug is in OllamaRefiner actually so look there only and report what you find in the "
        "code.",
        "The bug is somewhere else actually so look there only and report what you find in the "
        "code.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: The bug is in OllamaRefiner actually so look there only and report what you "
        "find in the code.",
    ),
    (
        "self-correction-reversed-identifier",
        "Rename OllamaRefiner to LocalRefiner no actually keep OllamaRefiner and just rename the "
        "method refined_text to guarded_text. And update the callers in cli/daemon.",
        "Rename OllamaRefiner to LocalRefiner. Keep refined_text and guarded_text; just update the "
        "callers in cli/daemon.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Rename OllamaRefiner to "
        "LocalRefiner no actually keep OllamaRefiner and just "
        "rename the method refined_text to guarded_text. And update the callers in cli/daemon.",
    ),
    (
        "self-correction-reversed-model",
        "For the benchmark maybe use gemma4:12b no wait maybe use qwen3:8b instead because it's "
        "already pulled and I think probably keep the temperature at 0.",
        "For the benchmark, maybe use qwen3:8b no wait maybe use gemma4:12b because it's already "
        "pulled, and probably keep the temperature at 0.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: For the benchmark maybe use gemma4:12b no wait maybe use qwen3:8b instead "
        "because it's already pulled and I think probably keep the temperature at 0.",
    ),
    (
        "contractions-dropped",
        "It won't matter much either way and it can't hurt to plan the migration first before we "
        "start.",
        "It will matter much either way and it can hurt to plan the migration first before we "
        "start.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: It won't matter much either way and it can't hurt to plan the migration "
        "first before we start.",
    ),
    (
        "negation-added",
        "Merge dev into main once the integration run is green and then tag the release please.",
        "Do not merge dev into main once the integration run is green and then tag the release "
        "please.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Merge dev into main once the integration run is green and then tag the "
        "release please.",
    ),
    (
        "name-dropped",
        "Ask Claude to review the parser changes in the lexer module and report back today.",
        "Ask to review the parser changes in the lexer module and report back today.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Ask Claude to review the parser changes in the lexer module and report back "
        "today.",
    ),
    (
        "noun-fix-turned-into-a-verb",
        "Um so I pushed a fix for the paste release guard last night. Validate it only.",
        "I pushed a fix for the paste release guard last night. Fix it again and validate it only.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Um so I pushed a fix for the paste release guard last night. Validate it "
        "only.",
    ),
    (
        "negated-verb-also-authorized",
        "Um can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding. Only plan it. Don't write any code. I mean we might end up not doing it at all "
        "you know.",
        "Can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding, then write the code once it's planned? Only plan it. Don't write any code. We "
        "might end up not doing it at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Um can you look at the hotkey module and just make a plan for how we'd "
        "support a second binding. Only plan it. Don't write any code. I mean we might end up not "
        "doing it at all you know.",
    ),
    (
        "negated-verb-authorized-in-place",
        "Um can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding. Only plan it. Don't write any code. I mean we might end up not doing it at all "
        "you know.",
        "Can you look at the hotkey module and just make a plan for how we'd support a second "
        "binding? Only plan it, then write it. Don't write any code. We might end up not doing it "
        "at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Um can you look at the hotkey module and just make a plan for how we'd "
        "support a second binding. Only plan it. Don't write any code. I mean we might end up not "
        "doing it at all you know.",
    ),
    (
        "lowercase-self-correction-reversed",
        "For the search in the tests directory use grep no wait use ripgrep and then summarize the "
        "matches for me.",
        "For the search in the tests directory, use grep and then summarize the matches for me.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: For the search in the tests directory use grep no wait use ripgrep and then "
        "summarize the matches for me.",
    ),
    (
        "head-noun-correction-reversed",
        "For the nightly benchmark run use the medium model no wait use the small model since the "
        "box has no GPU and then write the numbers to the report file for me please.",
        "For the nightly benchmark run, use the medium model since the box has no GPU and then "
        "write the numbers to the report file for me.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: For the nightly benchmark run use the medium model no wait use the small "
        "model since the box has no GPU and then write the numbers to the report file for me "
        "please.",
    ),
    (
        "head-noun-correction-reversed-after-sorry",
        "Compare the staging logs sorry the "
        "production logs against last week and summarize any new "
        "errors you see.",
        "Compare the staging logs against last week and summarize any new errors you see.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Compare the staging logs sorry the production logs against last week and "
        "summarize any new errors you see.",
    ),
    (
        "for-now-dropped",
        "I think the thing is the overlay flickers when the aura starts. It might be the timer or "
        "it might be the repaint. Just investigate it for now and um explain what you find. Don't "
        "touch overlay/platform at all.",
        "I think the overlay flickers when the aura starts. It might be the timer or it might be "
        "the repaint. Just investigate it and explain what you find. Don't touch overlay/platform "
        "at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I think the thing is the overlay flickers when the aura starts. It might be "
        "the timer or it might be the repaint. Just investigate it for now and um explain what you "
        "find. Don't touch overlay/platform at all.",
    ),
    (
        "sentence-initial-no-dropped",
        "No retries. Just log the failure and move on to the next file in the import queue.",
        "Just log the failure and move on to the next file in the import queue.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: No retries. Just log the failure and move on to the next file in the import "
        "queue.",
    ),
    (
        "real-question-made-a-statement",
        "Why does the daemon take 3 seconds to start on this machine? Is it the model load?",
        "The daemon takes 3 seconds to start on this machine. It is the model load.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Why does the daemon take 3 "
        "seconds to start on this machine? Is it the model "
        "load?",
    ),
    (
        "quoted-words-changed-beside-a-moved-comma",
        'The error says "output changed dictated wording or order" and I want I want the log line '
        "to keep that exact string. Like don't reword it at all.",
        'The error says "output changed the dictated '
        'wording," and I want the log line to keep that '
        "exact string. Don't reword it at all.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        'spoken input: The error says "output changed dictated wording or order" and I want I want '
        "the log line to keep that exact string. Like don't reword it at all.",
    ),
    (
        "can-we-question-made-a-command",
        "Can we merge the paste guard branch into dev today or is it too risky?",
        "Merge the paste guard branch into dev today.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Can we merge the paste guard branch into dev today or is it too risky?",
    ),
    (
        "can-we-question-made-a-command-without-a-clause",
        "Can we merge the paste guard branch into dev today before the release goes out?",
        "Merge the paste guard branch into dev today before the release goes out.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Can we merge the paste guard branch into dev today before the release goes "
        "out?",
    ),
    (
        "opinion-question-made-a-claim",
        "Would you say the cache layer in the export pipeline is the main problem here?",
        "The cache layer in the export pipeline is the main problem here.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Would you say the cache layer in the export pipeline is the main problem "
        "here?",
    ),
    (
        "no-before-a-slashed-word-dropped",
        "No I/O in the hot path of the refine guard, keep it pure and review the helpers.",
        "I/O in the hot path of the refine guard, keep it pure and review the helpers.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: No I/O in the hot path of the refine guard, keep it pure and review the "
        "helpers.",
    ),
    (
        "no-before-a-hyphenated-word-dropped",
        "No so-called quick fixes in the guard this time, review the design first.",
        "So-called quick fixes in the guard this time, review the design first.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: No so-called quick fixes in the guard this time, review the design first.",
    ),
    (
        "two-word-head-correction-reversed",
        "Use the old retry logic sorry the new retry logic in the update check and explain the "
        "backoff.",
        "Use the old retry logic in the update check and explain the backoff.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use the old retry logic sorry the new retry logic in the update check and "
        "explain the backoff.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:0",
        "If the check fails, only review it.",
        "Only review it.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: If the check fails, only review it.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:1",
        "Validate the proposal only.",
        "Check the proposal only.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Validate the proposal only.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:2",
        "Investigate the failure.",
        "Investigation of the failure.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Investigate the failure.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:3",
        "Maybe the cache failed.",
        "The cache failed.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Maybe the cache failed.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:4",
        "Don't change the timeout.",
        "Change the timeout.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Don't change the timeout.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:5",
        "Use --dry-run on /tmp/demo.",
        "Use --force on /tmp/demo.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use --dry-run on /tmp/demo.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:6",
        'Keep "dry run" in ClientID.',
        'Keep "run" in ClientID.',
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        'spoken input: Keep "dry run" in ClientID.',
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:7",
        "Use qwen3:8b for review.",
        "Use qwen3:4b for review.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Use qwen3:8b for review.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:8",
        "The limit is 30. The timeout is 30.",
        "The limit and timeout are 40.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: The limit is 30. The timeout is 30.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:9",
        "The limit is 30 for database requests. Separately the timeout is 30 no wait 40.",
        "The limit and timeout are 40.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: The limit is 30 for database requests. Separately the timeout is 30 no wait "
        "40.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:10",
        "Review the log.",
        "Repair the log.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: Review the log.",
    ),
    (
        "test_agent_rewrite.py:test_agent_retains_distinct_values_and_boundary_words:11",
        "I sent a repair for review.",
        "Fix the defect for review.",
        "Preserve every fact, request, uncertainty, condition, and authorization limit in the "
        "spoken input: I sent a repair for review.",
    ),
    (
        "introduced-name",
        "Contact Codex about the request.",
        "Contact Codex and Microsoft about the request.",
        "Contact Codex about the request; do not add Microsoft.",
    ),
)
