# SPDX-License-Identifier: GPL-3.0-or-later
"""Predeclared single-variable comparisons for the first screen."""

from __future__ import annotations

from transcription_study.records import Profile

PROFILES = {
    profile.id: profile
    for profile in (
        Profile("baseline"),
        Profile("gain_minus6", audio={"gain_db": -6}),
        Profile("gain_plus6", audio={"gain_db": 6}),
        Profile("gain_plus12", audio={"gain_db": 12}),
        Profile("normalize_minus24", audio={"normalize_rms_dbfs": -24}),
        Profile("vad_threshold035", vad={"threshold": 0.35}),
        Profile("vad_padding500", vad={"speech_pad_ms": 500}),
        Profile("beam3", decode={"beam_size": 3}),
        Profile("repeat0", decode={"no_repeat_ngram_size": 0}),
        Profile("gate0", gate_rms=0),
        Profile("gate0001", gate_rms=0.0001),
        Profile("vad_disabled", decode={"vad_filter": False}),
        Profile("post_gate09", post_silence_threshold=0.9),
        Profile("no_speech09", decode={"no_speech_threshold": 0.9}),
        Profile("prefix500", audio={"leading_ms": 500}),
        Profile("channel_mean", audio={"channel": "mean"}),
        Profile("channel_last", audio={"channel": "last"}),
    )
}


def select_clips(manifest: dict, split: str, limit: int) -> list[dict]:
    """Balance speech 2:1:1, then append explicit nonspeech controls when space remains."""
    candidates = [clip for clip in manifest["clips"] if clip["split"] == split]
    speech_corpora = ("ami", "librispeech_clean", "librispeech_other")
    allowed_corpora = {*speech_corpora, "synthetic_nonspeech"}
    if any(clip["corpus"] not in allowed_corpora for clip in candidates):
        raise ValueError("unsupported_corpus")
    buckets = {}
    for corpus in speech_corpora:
        buckets[corpus] = sorted(
            [clip for clip in candidates if clip["corpus"] == corpus],
            key=lambda clip: (clip.get("selection_order", 0), clip["id"]),
        )
    selected = []
    while len(selected) < limit and any(buckets.values()):
        for corpus in ("ami", "ami", "librispeech_clean", "librispeech_other"):
            if buckets[corpus] and len(selected) < limit:
                selected.append(buckets[corpus].pop(0))
    controls = sorted(
        [clip for clip in candidates if clip["corpus"] == "synthetic_nonspeech"],
        key=lambda clip: (clip.get("selection_order", 0), clip["id"]),
    )
    selected.extend(controls[: max(0, limit - len(selected))])
    return selected
