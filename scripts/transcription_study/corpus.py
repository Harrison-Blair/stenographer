# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare a pinned, speaker-disjoint public corpus without playing audio.

Run with ``.venv/bin/python -m scripts.transcription_study.corpus --download``.
References are corpus assets; no reference text or audio is printed or logged.
"""

import argparse
import hashlib
import io
import json
import random
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

SEED = 20260912
AMI_ROOT = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus"
ANNOTATIONS_URL = "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip"
CORPORA = ("ami", "librispeech_clean", "librispeech_other")
# Published at https://www.openslr.org/resources/12/md5sum.txt.
LIBRI_MD5 = {
    "clean": "32fa31d27d2e1cad72775fee3f4849a9",
    "other": "fb5a50374b501bb3bac4815ee91d3135",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def balanced_order(clips: list[dict]) -> list[dict]:
    """Interleave 2 conversational, 1 clean, 1 difficult utterance."""
    pools = {name: [clip for clip in clips if clip["corpus"] == name] for name in CORPORA}
    ordered = []
    while any(pools.values()):
        for name in ("ami", "ami", "librispeech_clean", "librispeech_other"):
            if pools[name]:
                ordered.append(pools[name].pop(0))
    return ordered


def disjoint_groups(clips: list[dict]) -> bool:
    groups = {
        split: {c["group"] for c in clips if c["split"] == split} for split in ("dev", "heldout")
    }
    speakers = {
        split: {c["speaker"] for c in clips if c["split"] == split and c.get("speaker")}
        for split in ("dev", "heldout")
    }
    return not (groups["dev"] & groups["heldout"] or speakers["dev"] & speakers["heldout"])


def group_words(words: list[tuple], pause: float = 0.4) -> list[list[tuple]]:
    groups: list[list[tuple]] = []
    for word in words:
        if not groups or word[0] - groups[-1][-1][1] > pause:
            groups.append([])
        groups[-1].append(word)
    return groups


def split_speakers(speakers: list[str]) -> dict[str, str]:
    """Balance a subset by seeded speaker rank; final manifest checks global leakage."""
    ranked = sorted(
        set(speakers),
        key=lambda speaker: hashlib.sha256(f"{SEED}:libri:{speaker}".encode()).hexdigest(),
    )
    return {
        speaker: "dev" if index < len(ranked) // 2 else "heldout"
        for index, speaker in enumerate(ranked)
    }


def download(url: str, target: Path, allow: bool) -> dict:
    """Cache a public asset atomically; fixed asset limits total at most 2.6 GB."""
    limit = 500_000_000 if url.endswith(".tar.gz") else 150_000_000
    if url.endswith(".zip"):
        limit = 100_000_000
    if not target.exists():
        if not allow:
            raise FileNotFoundError(f"Missing public asset {target.name}; use --download")
        partial = target.with_suffix(target.suffix + ".part")
        count = 0
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as stream:
            if int(response.headers.get("Content-Length", 0)) > limit:
                raise ValueError("Asset exceeds per-download limit")
            while block := response.read(1024 * 1024):
                count += len(block)
                if count > limit:
                    raise ValueError("Asset exceeds per-download limit")
                stream.write(block)
        partial.replace(target)
    if target.stat().st_size > limit:
        raise ValueError("Cached asset exceeds per-download limit")
    return {
        "url": url,
        "path": str(target),
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def write_clip(
    root: Path, identity: str, audio, reference: str, metadata: dict, rate: int = 16000
) -> dict:
    wav = root / "clips" / f"{identity}.wav"
    ref = root / "references" / f"{identity}.txt"
    sf.write(wav, audio, rate, subtype="PCM_16")
    ref.write_text(reference.strip() + "\n", encoding="utf-8")
    return {
        "id": identity,
        "audio_path": str(wav),
        "reference_path": str(ref),
        "sha256": sha256(wav),
        "reference_sha256": sha256(ref),
        "duration_seconds": len(audio) / rate,
        "sample_rate": rate,
        **metadata,
    }


def ami_clips(root: Path, archive: Path) -> tuple[list[dict], list[dict]]:
    clips, variants = [], []
    with zipfile.ZipFile(archive) as annotations:
        meetings = ET.fromstring(annotations.read("corpusResources/meetings.xml"))
        selected_speakers: dict[str, set] = {}
        for meeting, split in (("ES2002a", "dev"), ("ES2003a", "heldout")):
            metadata = next(e for e in meetings if e.get("observation") == meeting)
            speakers = {s.get("nxt_agent"): s.attrib for s in metadata}
            selected_speakers[split] = {s["global_name"] for s in speakers.values()}
            word_tracks = {}
            for agent in sorted(speakers):
                xml = ET.fromstring(annotations.read(f"words/{meeting}.{agent}.words.xml"))
                word_tracks[agent] = [
                    (float(w.attrib["starttime"]), float(w.attrib["endtime"]), w.text.strip())
                    for w in xml
                    if w.tag == "w" and w.get("punc") != "true" and w.text and w.get("starttime")
                ]
            candidates = []
            for agent, words in word_tracks.items():
                for chunk in group_words(words):
                    start, end = max(0, chunk[0][0] - 0.25), chunk[-1][1] + 0.25
                    if not (1 <= len(chunk) <= 60 and 0.5 <= end - start <= 15):
                        continue
                    overlaps = any(
                        w[0] < end and w[1] > start
                        for other, track in word_tracks.items()
                        if other != agent
                        for w in track
                    )
                    if not overlaps:
                        candidates.append((agent, start, end, chunk))
            random.Random(f"{SEED}:{meeting}").shuffle(candidates)
            # Round-robin participants to avoid selecting a single dominant speaker.
            chosen = []
            for minimum_words in (3, 1):
                pools = {
                    agent: [
                        c
                        for c in candidates
                        if c[0] == agent and len(c[3]) >= minimum_words and c not in chosen
                    ]
                    for agent in speakers
                }
                while len(chosen) < 30 and any(pools.values()):
                    for agent in sorted(pools):
                        if pools[agent] and len(chosen) < 30:
                            chosen.append(pools[agent].pop())
            if len(chosen) != 30:
                raise ValueError(f"Only {len(chosen)} eligible turns for {meeting}")
            for i, (agent, start, end, words) in enumerate(chosen):
                speaker = speakers[agent]
                identity = f"ami-{meeting}-{agent}-{i:02d}"
                reference = " ".join(w[2] for w in words)
                for capture in (f"Headset-{speaker['channel']}", "Array1-01"):
                    wav = root / "downloads" / f"{meeting}.{capture}.wav"
                    audio, rate = sf.read(
                        wav, start=round(start * 16000), stop=round(end * 16000), dtype="float32"
                    )
                    if rate != 16000 or audio.ndim != 1:
                        raise ValueError("Expected official AMI 16kHz mono recording")
                    info = {
                        "split": split,
                        "corpus": "ami",
                        "group": f"ami:{meeting[:-1]}",
                        "speaker": f"ami:{speaker['global_name']}",
                        "meeting": meeting,
                        "capture": capture,
                        "source_url": f"{AMI_ROOT}/{meeting}/audio/{meeting}.{capture}.wav",
                        "start_seconds": start,
                        "end_seconds": end,
                        "overlap": False,
                        "boundary_padding_seconds": 0.25,
                        "word_count": len(words),
                        "reference_source": f"words/{meeting}.{agent}.words.xml",
                        "license": "CC-BY-4.0",
                    }
                    if capture == "Array1-01":
                        info["variant_of"] = identity
                        variants.append(write_clip(root, f"{identity}-far", audio, reference, info))
                    else:
                        clips.append(write_clip(root, identity, audio, reference, info))
        if selected_speakers["dev"] & selected_speakers["heldout"]:
            raise ValueError("AMI speaker leakage between splits")
    return clips, variants


def libri_clips(root: Path, subset: str) -> list[dict]:
    """Select one utterance per speaker from a balanced seeded partition."""
    result = []
    archive = root / "downloads" / f"test-{subset}.tar.gz"
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        references = {}
        for member in members:
            if member.name.endswith(".trans.txt"):
                with source.extractfile(member) as stream:
                    for line in stream.read().decode("utf-8").splitlines():
                        identity, reference = line.split(" ", 1)
                        references[identity] = reference
        candidates = {"dev": {}, "heldout": {}}
        partitions = split_speakers(
            [Path(m.name).stem.split("-")[0] for m in members if m.name.endswith(".flac")]
        )
        for member in members:
            if not member.name.endswith(".flac"):
                continue
            identity = Path(member.name).stem
            speaker = identity.split("-")[0]
            split = partitions[speaker]
            candidates[split].setdefault(speaker, []).append(member)
        for split in ("dev", "heldout"):
            speakers = sorted(candidates[split])
            rng = random.Random(f"{SEED}:libri:{subset}:{split}")
            rng.shuffle(speakers)
            count = 0
            for speaker in speakers:
                options = candidates[split][speaker]
                rng.shuffle(options)
                for member in options:
                    with source.extractfile(member) as stream:
                        audio, rate = sf.read(io.BytesIO(stream.read()), dtype="float32")
                    if rate != 16000 or not 2 <= len(audio) / rate <= 12:
                        continue
                    identity = Path(member.name).stem
                    result.append(
                        write_clip(
                            root,
                            f"libri-{subset}-{identity}",
                            audio,
                            references[identity],
                            {
                                "split": split,
                                "corpus": f"librispeech_{subset}",
                                "group": f"libri:{speaker}",
                                "speaker": f"libri:{speaker}",
                                "source_url": f"https://www.openslr.org/resources/12/test-{subset}.tar.gz",
                                "archive_member": member.name,
                                "license": "CC-BY-4.0",
                            },
                        )
                    )
                    count += 1
                    break
                if count == 15:
                    break
            if count != 15:
                raise ValueError(f"Only {count} eligible LibriSpeech {subset}/{split} speakers")
    return result


def prepare(root: Path, allow_download: bool) -> dict:
    root = root.resolve()
    for directory in ("downloads", "clips", "references"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    urls = [ANNOTATIONS_URL]
    urls.extend(
        f"https://www.openslr.org/resources/12/test-{subset}.tar.gz"
        for subset in ("clean", "other")
    )
    urls.extend(
        f"{AMI_ROOT}/{meeting}/audio/{meeting}.{capture}.wav"
        for meeting in ("ES2002a", "ES2003a")
        for capture in ("Headset-0", "Headset-1", "Headset-2", "Headset-3", "Array1-01")
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        assets = list(
            pool.map(
                lambda url: download(
                    url, root / "downloads" / url.rsplit("/", 1)[1], allow_download
                ),
                urls,
            )
        )
    byte_count = sum(asset["bytes"] for asset in assets)
    if byte_count > 3_000_000_000:
        raise ValueError("Corpus assets exceed the reserved 3GB campaign budget")
    for subset, expected in LIBRI_MD5.items():
        with (root / "downloads" / f"test-{subset}.tar.gz").open("rb") as stream:
            actual = hashlib.file_digest(stream, "md5").hexdigest()
        if actual != expected:
            raise ValueError(f"Public LibriSpeech {subset} archive checksum mismatch")
    clips, variants = ami_clips(root, root / "downloads" / "ami_public_manual_1.6.2.zip")
    for subset in ("clean", "other"):
        clips.extend(libri_clips(root, subset))
    if not disjoint_groups(clips):
        raise ValueError("Source-group or speaker leakage between splits")
    clips = [
        {**clip, "selection_order": index}
        for split in ("dev", "heldout")
        for index, clip in enumerate(balanced_order([c for c in clips if c["split"] == split]))
    ]
    manifest = {
        "version": 1,
        "seed": SEED,
        "download_bytes": byte_count,
        "downloads": assets,
        "librispeech_publisher_md5": LIBRI_MD5,
        "licenses": {
            "ami": "https://groups.inf.ed.ac.uk/ami/download/",
            "librispeech": "https://www.openslr.org/12/",
        },
        "selection": {
            "ami": (
                "Two disjoint meeting groups, nonoverlapping pause-bounded turns, "
                "1-60 words, 0.5-15s, 250ms margins; round-robin speakers; "
                "prefer >=3 words, fill remaining slots with shorter turns"
            ),
            "librispeech": (
                "test-clean and test-other, seeded balanced speaker ranking per subset, "
                "one utterance per selected speaker, 2-12s; global speaker leakage checked"
            ),
            "limitations": (
                "AMI covers only two scenario meetings; public read speech does not model "
                "reduced articulation; no manually audited semantic tags"
            ),
        },
        "clips": clips,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "variants.json").write_text(
        json.dumps({"version": 1, "seed": SEED, "clips": variants}, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def prepare_controls(root: Path) -> dict:
    """Write dev-only synthetic controls without rewriting the primary manifest."""
    root = root.resolve()
    primary = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    parents = balanced_order([c for c in primary["clips"] if c["split"] == "dev"])[:4]
    if [c["corpus"] for c in parents] != ["ami", "ami", "librispeech_clean", "librispeech_other"]:
        raise ValueError("Stress controls require a balanced four-utterance development panel")
    clips = []
    rng = np.random.default_rng(SEED)
    for parent in parents:
        audio, rate = sf.read(parent["audio_path"], dtype="float32")
        if rate != 16000 or audio.ndim != 1:
            raise ValueError("Stress controls require mono 16kHz source clips")
        reference = Path(parent["reference_path"]).read_text(encoding="utf-8")
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        noise = rng.standard_normal(len(audio))
        noise *= rms / np.sqrt(np.mean(noise**2)) / np.sqrt(10)
        noisy = audio.astype(np.float64) + noise
        noise_scale = min(1.0, 0.9989999 / max(float(np.max(np.abs(noisy))), 1e-12))
        signals = (
            ("tail", audio),
            ("quiet-tail", audio * 0.1),
            ("noise10-tail", noisy * noise_scale),
        )
        for label, signal in signals:
            metadata = {
                key: value
                for key, value in parent.items()
                if key not in {"id", "audio_path", "reference_path", "sha256", "reference_sha256"}
            }
            metadata.update(
                variant_of=parent["id"],
                control=label,
                selection_order=len(clips),
                tail_silence_seconds=3,
                reference_words=len(reference.split()),
                synthetic=True,
            )
            if label == "quiet-tail":
                metadata["gain_db"] = -20
            if label == "noise10-tail":
                metadata.update(
                    snr_db=10, noise_reference="whole source-clip RMS", peak_scale=noise_scale
                )
            # write_clip owns derived length; discard the inherited source duration.
            metadata.pop("duration_seconds", None)
            clips.append(
                write_clip(
                    root, f"{parent['id']}-{label}", np.pad(signal, (0, 48000)), reference, metadata
                )
            )
    silence = np.zeros(48000, dtype=np.float32)
    clicks = silence.copy()
    clicks[[4000, 16000, 32000]] = [0.2, -0.2, 0.2]
    nonspeech = (
        ("silence", silence),
        ("noise-low", rng.standard_normal(48000).astype(np.float32) * 0.005),
        ("noise-high", rng.standard_normal(48000).astype(np.float32) * 0.02),
        ("clicks", clicks),
    )
    for label, signal in nonspeech:
        clips.append(
            write_clip(
                root,
                f"control-{label}",
                signal,
                "",
                {
                    "split": "dev",
                    "corpus": "synthetic_nonspeech",
                    "group": f"control:{label}",
                    "source_url": "",
                    "synthetic": True,
                    "control": label,
                    "reference_words": 0,
                    "selection_order": len(clips),
                },
            )
        )
    manifest = {
        "version": 1,
        "seed": SEED,
        "primary_manifest_sha256": sha256(root / "manifest.json"),
        "purpose": (
            "Synthetic quiet/noisy/tail controls; these do not reproduce reduced articulation"
        ),
        "clips": clips,
    }
    (root / "controls.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".cache/transcription-study-20260912"))
    parser.add_argument(
        "--download", action="store_true", help="Explicitly fetch public corpus assets"
    )
    parser.add_argument(
        "--controls", action="store_true", help="Derive stress controls from an existing manifest"
    )
    args = parser.parse_args()
    if args.controls:
        manifest = prepare_controls(args.root)
        print(json.dumps({"control_clips": len(manifest["clips"])}))
        return
    manifest = prepare(args.root, args.download)
    print(
        json.dumps({"clips": len(manifest["clips"]), "download_bytes": manifest["download_bytes"]})
    )


if __name__ == "__main__":
    main()
