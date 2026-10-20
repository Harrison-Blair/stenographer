# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording order and leakage-safe prompts for context experiments."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def recording_key(clip: dict) -> str:
    """Identify the source recording without merging distinct AMI tracks."""
    if clip.get("meeting") and clip.get("capture"):
        return f"ami:{clip['meeting']}:{clip['capture']}"
    member = clip.get("archive_member")
    if member:
        parts = Path(member).parts
        if len(parts) >= 3:
            return f"librispeech:{parts[-3]}:{parts[-2]}"
    return f"clip:{clip['id']}"


def _recording_order(clip: dict) -> tuple[float | int, str]:
    if clip.get("start_seconds") is not None:
        return float(clip["start_seconds"]), clip["id"]
    member = clip.get("archive_member", "")
    suffix = Path(member).stem.rsplit("-", 1)[-1]
    if suffix.isdigit():
        return int(suffix), clip["id"]
    return int(clip.get("selection_order", 0)), clip["id"]


def recording_groups(clips: list[dict]) -> list[list[dict]]:
    """Return clips in stable recording groups and source order."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for clip in clips:
        groups[recording_key(clip)].append(clip)
    return [sorted(groups[key], key=_recording_order) for key in sorted(groups)]


def build_prompt(
    target: dict,
    prior_clips: list[dict],
    *,
    references: dict[str, str],
    decoded: dict[str, str],
    mode: str,
) -> tuple[str | None, list[str]]:
    """Build a prompt from at most three earlier clips of the same recording."""
    if mode not in {"off", "reference", "decoded"}:
        raise ValueError("unknown context mode")
    if mode == "off":
        return None, []
    target_id = target["id"]
    target_recording = recording_key(target)
    if any(clip["id"] == target_id for clip in prior_clips):
        raise ValueError("target clip cannot be context")
    if any(recording_key(clip) != target_recording for clip in prior_clips):
        raise ValueError("context clips must come from the same recording")
    ordered = sorted(prior_clips, key=_recording_order)
    if prior_clips != ordered:
        raise ValueError("context clips must be in recording order")
    sources = references if mode == "reference" else decoded
    recent = prior_clips[-3:]
    source_ids = [clip["id"] for clip in recent]
    prompt = " ".join(
        sources[clip_id].strip() for clip_id in source_ids if sources.get(clip_id, "").strip()
    )
    return prompt or None, source_ids
