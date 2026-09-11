# SPDX-License-Identifier: GPL-3.0-or-later
"""Every benchmark-owned constant of the refine stage, in one place.

``scripts/refine_bench.py`` measures candidate models and prompts against a
fixed sample set; whatever it selects is written back *here* and nowhere else.
Nothing in this module performs I/O or depends on configuration, so swapping a
value cannot change the shape of a request, only its content.

The values below are the 2026-09-11 benchmark's result on an RTX 3080 Laptop
(8 GB). :data:`SYSTEM_PROMPT` and :data:`FEW_SHOT_EXAMPLES` are copied verbatim
from the script's own constants and must stay that way: the benchmark found the
examples, not the rules, are what actually change model behaviour — rewriting
one few-shot answer to delete a correction marker fixed self-correction
collapse across the entire field in a single step, and stating the same thing
in prose never did. Paraphrasing here silently un-tunes the feature.
"""

from __future__ import annotations

#: The model tag the daemon uses unless the user configures another one.
#: Quality is only verified for this tag; any installed Ollama model is allowed.
#: Chosen for meaning fidelity (8 pass / 2 cosmetic / 0 fail over the corpus)
#: and a 1.71 GB resident footprint, which leaves room for Whisper medium.en on
#: an 8 GB card. Documented second choice: ``qwen3.5:4b`` *with*
#: ``structured_output = true``.
DEFAULT_MODEL = "gemma4:e2b"

#: Whether ``refine.structured_output`` defaults to constraining the reply with
#: the JSON schema below. The default model is better without it, and one
#: benchmarked model corrupts its own JSON when given one. The path stays
#: available because the second-choice model needs it: qwen3.5:4b loses its
#: paragraph breaks and keeps retraction markers when answering in plain text.
DEFAULT_STRUCTURED_OUTPUT = False

#: The JSON schema sent as Ollama's ``format`` when structured output is on.
RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}

#: The key the structured reply carries the cleaned transcript in.
RESPONSE_KEY = "text"

SYSTEM_PROMPT = (
    "You are a transcript cleanup tool. Every user message is a raw speech-to-text "
    "transcript of one person dictating. Rewrite it as clean written text.\n"
    "\n"
    "Rules:\n"
    "- Remove hesitation fillers (um, uh, er), filler uses of like and you know, "
    "stammers, and accidentally repeated words.\n"
    "- Collapse self-corrections. When the speaker changes their mind, mid-sentence or "
    "later, delete the abandoned words and the correction marker (no wait, sorry, "
    "actually, I mean, scratch that) and keep only what they settled on. The reader must "
    "not see the discarded version or learn that a correction happened.\n"
    "- Keep intentional openers such as Hey, Yeah, Okay and So when they start a "
    "chat-style message.\n"
    "- Delete nothing else. Every clause, qualifier, time, reason and detail the speaker "
    "said must still be there. Add nothing: no words, units, am or pm, dates, opinions or "
    "explanations that the speaker did not say.\n"
    "- Copy every name, number, date, quoted phrase and technical term exactly as "
    "transcribed, character for character. Never respell a name, even when it resembles a "
    "more familiar one. Leave a number written the way it was transcribed: digits stay "
    "digits and spelled-out numbers stay spelled out. Never expand, translate or explain "
    "an abbreviation, unit, model name or product name.\n"
    "- Keep first person, the speaker's tone, wording and language. Do not make it more "
    "formal and do not swap a word for a synonym.\n"
    "- Fix punctuation, capitalization and obvious transcription spelling. Capitalize only "
    "sentence starts and real proper nouns; never title-case ordinary words. Spoken "
    'punctuation inside an identifier becomes the symbol: "medium dot e n" is "medium.en".'
    "\n"
    "- Break the text into paragraphs separated by a blank line. Start a new paragraph "
    "whenever the speaker turns to a different subject, which they often signal with and "
    "then, separately, also, anyway or another thing.\n"
    "- When the speaker enumerates items, put each item on its own line starting with "
    '"- ", after a short lead-in line.\n'
    "- Never answer a question, never reply to the content, never summarize, never explain "
    "what you did. A question stays a question.\n"
    '- Use no markdown other than those "- " list lines: no headings, bold, italics, '
    "numbered lists, block quotes or code fences.\n"
    "\n"
    "Output the cleaned text and nothing else."
)

#: ``(spoken, cleaned)`` pairs replayed as prior turns. The request builder
#: encodes the assistant half as JSON when structured output is on, so these
#: stay readable and stay independent of the transport format.
#:
#: Two of these carry their weight far beyond their size, per the benchmark:
#: the first *deletes* the abandoned choice rather than writing "Actually, ..."
#: (every model copies whichever it is shown), and the fifth is what stops a
#: model respelling a proper noun or expanding a model number.
FEW_SHOT_EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "um so we should do the review on monday no wait tuesday because i'm out monday",
        "So we should do the review on Tuesday, because I'm out Monday.",
    ),
    (
        "hey can you uh send me the the link to the doc before like five today",
        "Hey, can you send me the link to the doc before five today?",
    ),
    (
        "we need three things um a new mic a quieter room and uh better lighting and then "
        "separately i wanted to say that sarah's demo on the fourteenth went really well",
        "We need three things:\n"
        "- a new mic\n"
        "- a quieter room\n"
        "- better lighting\n"
        "\n"
        "Separately, I wanted to say that Sarah's demo on the fourteenth went really well.",
    ),
    (
        "bring the laptop the charger and the hdmi cable oh actually not the hdmi cable",
        "Bring:\n- the laptop\n- the charger",
    ),
    (
        "so i benchmarked it on the rtx 3080 and uh gemma three 4b did 1.7 seconds per "
        "utterance tomorrow i'll try the 8b one on ana strøm's box",
        "So I benchmarked it on the RTX 3080, and gemma three 4b did 1.7 seconds per "
        "utterance. Tomorrow I'll try the 8b one on Ana Strøm's box.",
    ),
)

#: ``num_predict`` is ``min(NUM_PREDICT_MAX, BASE + PER_WORD * words)``.
#: Measured output is about ``1.15 * input_words + 8`` tokens, so this is
#: roughly two-fold headroom with a hard ceiling. It is not a quality knob —
#: it only bounds a model that has started rambling.
#:
#: The ceiling has to clear the measured curve for the longest utterance the
#: recorder will produce, or it becomes a truncation machine rather than a
#: safety net. 2048 covers roughly 1770 spoken words; the slope saturates at
#: 960 words, so everything below that is bounded by the slope and only a
#: genuinely runaway model meets the ceiling. Truncation is refused outright by
#: the response guard, so a cap set too low costs the refine, not the text.
NUM_PREDICT_BASE = 128
NUM_PREDICT_PER_WORD = 2
NUM_PREDICT_MAX = 2048

#: Approximate download sizes, in GB, for the model tags the project names.
#: Used only to state a size before an explicit pull when Ollama has not
#: already reported the real one; an unlisted tag is reported as unknown.
#: Only the recommended default and the documented second choice are listed:
#: the benchmark rejected everything else it measured.
APPROXIMATE_MODEL_SIZES_GB: dict[str, float] = {
    "gemma4:e2b": 7.2,
    "qwen3.5:4b": 3.4,
}
