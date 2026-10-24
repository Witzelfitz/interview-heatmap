from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .common import cached, digest, file_hash


def run(command):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg/ffprobe fehlt. Installation siehe README.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Medienverarbeitung fehlgeschlagen: {exc.stderr[-2000:]}") from exc


def prepare(source: Path, out: Path):
    probe = json.loads(
        run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)])
    )
    if not any(s["codec_type"] == "audio" for s in probe["streams"]):
        raise ValueError("Die Mediendatei enthält keine Audiospur.")
    sha = file_hash(source)
    wav = out / "audio.wav"
    stamp = out / "cache" / "audio.json"
    key = digest({"sha": sha, "format": "16k-mono-pcm16-v1"})

    def extract():
        temporary = out / "audio.tmp.wav"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ]
        )
        temporary.replace(wav)
        return {"wav_hash": file_hash(wav)}

    if not wav.exists():
        stamp.unlink(missing_ok=True)
    prepared = cached(stamp, key, extract)
    if file_hash(wav) != prepared["wav_hash"]:
        stamp.unlink()
        cached(stamp, key, extract)
    info = sf.info(wav)
    video = next(
        (
            s
            for s in probe["streams"]
            if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    return wav, {
        "filename": source.name,
        "sha256": sha,
        "duration": info.duration,
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "media_type": "video" if video else "audio",
        "source_frame_rate": video.get("avg_frame_rate") if video else None,
        "source_timecode": probe["format"].get("tags", {}).get("timecode", "00:00:00:00"),
    }


def overlap_duration(start, end, turns):
    events = []
    for turn in turns:
        a, b = max(start, turn["start"]), min(end, turn["end"])
        if b > a:
            events.extend([(a, 1), (b, -1)])
    active, last, total = 0, start, 0.0
    for t, delta in sorted(events):
        if active > 1:
            total += t - last
        active += delta
        last = t
    return total


def features(wav: Path, segments, turns):
    import librosa

    result, previous_end = [], 0.0
    with sf.SoundFile(wav) as stream:
        sr = stream.samplerate
        for segment in segments:
            start, end = segment["start"], segment["end"]
            stream.seek(int(start * sr))
            audio = stream.read(max(1, int((end - start) * sr)), dtype="float32")
            rms = float(np.sqrt(np.mean(audio.astype("float64") ** 2))) if audio.size else 0.0
            pitch_variance = None
            if len(audio) >= 2048 and rms > 1e-5:
                f0 = librosa.yin(audio, fmin=65, fmax=600, sr=sr, frame_length=1024, hop_length=320)
                energy = librosa.feature.rms(y=audio, frame_length=1024, hop_length=320)[0]
                valid = f0[: len(energy)][energy[: len(f0)] > max(rms * 0.3, 1e-4)]
                # Log-Hz / Halbtöne verhindern, dass eine hohe Grundstimme automatisch gewinnt.
                if valid.size >= 3:
                    pitch_variance = float(np.var(12 * np.log2(valid / 65)))
            result.append(
                {
                    "segment_id": segment["id"],
                    "speaker": segment["speaker"],
                    "rms": rms,
                    "pitch_variance": pitch_variance,
                    "words_per_second": len(segment["words"]) / max(0.1, end - start),
                    "pause_before": max(0.0, start - previous_end),
                    "overlap_seconds": overlap_duration(start, end, turns),
                    "laughter": None,
                }
            )
            previous_end = max(previous_end, end)
    metrics = ["rms", "pitch_variance", "words_per_second", "pause_before", "overlap_seconds"]
    for speaker in {s["speaker"] for s in segments}:
        rows = [r for r in result if r["speaker"] == speaker]
        for metric in metrics:
            values = [r[metric] for r in rows if r[metric] is not None]
            mean, std = (float(np.mean(values)), float(np.std(values))) if values else (0.0, 0.0)
            for row in rows:
                row.setdefault("z", {})[metric] = (
                    float(np.clip((row[metric] - mean) / std, -3, 3))
                    if row[metric] is not None and std > (0.1 if metric == "pitch_variance" else 1e-8)
                    else 0.0
                )
    for row in result:
        z = row["z"]
        combined = 0.35 * z["rms"] + 0.25 * z["pitch_variance"] + 0.2 * z["words_per_second"]
        combined += 0.15 * z["pause_before"] + 0.05 * z["overlap_seconds"]
        row["audio_score"] = float(1 / (1 + np.exp(-combined)))
    return result
