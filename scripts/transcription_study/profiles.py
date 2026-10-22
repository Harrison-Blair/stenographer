# SPDX-License-Identifier: GPL-3.0-or-later
"""Balanced clip selection for the study corpus."""

from __future__ import annotations


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
