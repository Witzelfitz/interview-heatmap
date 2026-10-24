from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

VERSION = "1"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def cached(path: Path, key: str, compute):
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("key") == key and saved.get("version") == VERSION:
            return saved["data"]
    data = compute()
    write_json(path, {"version": VERSION, "key": key, "data": data})
    return data


def swiss(text: str) -> str:
    return text.replace("ß", "ss").replace("ẞ", "SS")


def timestamp(seconds: float, srt=False) -> str:
    millis = round(seconds * 1000)
    h, rest = divmod(millis, 3600000)
    m, rest = divmod(rest, 60000)
    s, ms = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02}{',' if srt else '.'}{ms:03}"


def export_transcript(transcript, directory: Path):
    write_json(directory / "transcript.json", transcript)
    srt, txt = [], []
    for i, s in enumerate(transcript["segments"], 1):
        srt.append(
            f"{i}\n{timestamp(s['start'], True)} --> {timestamp(s['end'], True)}\n"
            f"{s['speaker']}: {s['text']}\n"
        )
        txt.append(f"[{timestamp(s['start'])}] {s['speaker']}: {s['text']}")
    (directory / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")
    (directory / "transcript.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")


def validate_transcript(segments, duration):
    ids = set()
    for segment in segments:
        if segment["id"] in ids:
            raise ValueError("Doppelte Segment-ID")
        ids.add(segment["id"])
        if not 0 <= segment["start"] < segment["end"] <= duration + 0.05:
            raise ValueError("Segment ausserhalb der Mediendauer")
        if not segment["words"]:
            raise ValueError("Segment ohne Wort-Zeitstempel: keine präzisen Schnitte möglich")
        last = segment["start"]
        for word in segment["words"]:
            a, b = word["start"], word["end"]
            if not segment["start"] - 0.001 <= a <= b <= segment["end"] + 0.001 or a < last - 0.001:
                raise ValueError("Ungültige oder unsortierte Wort-Zeitstempel")
            last = b
