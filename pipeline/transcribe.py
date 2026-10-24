from __future__ import annotations

import gc
import json
import logging
import math
import os
import tempfile
import wave
from pathlib import Path

from .common import swiss

log = logging.getLogger(__name__)


def local_transcribe(
    wav: Path, language: str, model_name: str, device: str, compute_type: str, offline=False
):
    import ctranslate2
    import psutil
    from faster_whisper import WhisperModel

    cuda = ctranslate2.get_cuda_device_count() > 0
    device = ("cuda" if cuda else "cpu") if device == "auto" else device
    if model_name == "auto":
        model_name = (
            "large-v3" if device == "cuda" and psutil.virtual_memory().available > 8 * 1024**3 else "medium"
        )
    compute_type = ("float16" if device == "cuda" else "int8") if compute_type == "auto" else compute_type
    log.info("Lokales Whisper-Modell: %s / %s / %s", model_name, device, compute_type)

    def execute(name, target_device, precision):
        model = WhisperModel(
            name,
            device=target_device,
            compute_type=precision,
            local_files_only=offline,
            cpu_threads=min(8, os.cpu_count() or 4),
        )
        iterator, info = model.transcribe(
            str(wav), language=language, beam_size=5, word_timestamps=True, vad_filter=True
        )
        words = []
        for segment in iterator:
            if segment.text.strip() and not segment.words:
                raise ValueError("Whisper lieferte Text ohne Wort-Zeitstempel.")
            for word in segment.words or []:
                if word.end > word.start and word.word.strip():
                    words.append(
                        {
                            "start": float(word.start),
                            "end": float(word.end),
                            "word": swiss(word.word.strip()),
                            "probability": float(word.probability),
                        }
                    )
            log.info("Transkribiert bis %.1f s", segment.end)
        return {
            "words": words,
            "language": info.language,
            "model": name,
            "device": target_device,
            "backend": "faster-whisper",
        }

    try:
        return execute(model_name, device, compute_type)
    except (RuntimeError, MemoryError) as exc:
        if "memory" not in str(exc).lower() and not isinstance(exc, MemoryError):
            raise
        if model_name not in {"large-v3", "large-v2", "large"}:
            raise
        log.warning("Zu wenig Speicher: neuer Versuch mit medium auf CPU/int8.")
        gc.collect()
        return execute("medium", "cpu", "int8")


def remote_transcribe(wav: Path, language: str):
    """WAV-Blöcke unter dem 25-MB-Limit; echte API-Zeiten um Blockoffset verschieben."""
    from openai import OpenAI

    log.warning("REMOTE: Audiodaten werden an OpenAI übermittelt. Einwilligung/Vertragsgrundlage prüfen.")
    client = OpenAI(timeout=180, max_retries=3)
    result = []
    with wave.open(str(wav), "rb") as source, tempfile.TemporaryDirectory() as directory:
        sr = source.getframerate()
        offset = 0.0
        while True:
            frames = source.readframes(sr * 600)
            if not frames:
                break
            chunk = Path(directory) / "chunk.wav"
            with wave.open(str(chunk), "wb") as target:
                target.setparams(source.getparams())
                target.writeframes(frames)
            with chunk.open("rb") as stream:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=stream,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            if response.text.strip() and not response.words:
                raise ValueError("Remote-API lieferte keine Wort-Zeitstempel.")
            result.extend(
                {"word": swiss(w.word.strip()), "start": offset + w.start, "end": offset + w.end}
                for w in response.words or []
                if w.end > w.start
            )
            offset += len(frames) / (sr * source.getsampwidth() * source.getnchannels())
    return {"words": result, "language": language, "model": "whisper-1", "backend": "openai-remote"}


def diarize(wav: Path, model_name: str, speakers: int | None = None, turns_file: Path | None = None):
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if turns_file:
        turns = json.loads(turns_file.read_text(encoding="utf-8"))
        if not isinstance(turns, list):
            raise ValueError("Sprecherdatei muss eine Liste aus {start, end, speaker} sein.")
    else:
        if model_name != "pyannote/speaker-diarization-community-1" and not Path(model_name).is_dir():
            raise ValueError(
                "Diarisierung erlaubt nur community-1 oder ein lokales Modellverzeichnis; "
                "gehostete pyannote-Pipelines sind ausgeschlossen."
            )
        try:
            import soundfile as sf
            import torch
            from pyannote.audio import Pipeline
            from pyannote.audio.pipelines import SpeakerDiarization
        except ImportError as exc:
            raise RuntimeError(
                "Diarisierung benötigt pip install '.[diarization]' und HF_TOKEN. "
                "Für genau eine Stimme: --single-speaker."
            ) from exc
        log.info("Lokale Diarisierung mit %s", model_name)
        try:
            pipeline = Pipeline.from_pretrained(model_name, token=os.environ.get("HF_TOKEN"))
        except Exception as exc:
            raise RuntimeError(
                "Lokales pyannote-Modell nicht ladbar. HF_TOKEN, akzeptierte Modellbedingungen "
                "und bei --offline die lokalen Modellgewichte prüfen."
            ) from exc
        if pipeline is None:
            raise RuntimeError("pyannote-Modell fehlt. HF_TOKEN und Modellfreigabe prüfen.")
        if not isinstance(pipeline, SpeakerDiarization):
            raise ValueError("Nur lokale SpeakerDiarization-Pipelines sind erlaubt.")
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
        # Übergabe als Tensor vermeidet zusätzliche Decoder-Abhängigkeiten.
        audio, sr = sf.read(wav, dtype="float32")
        kwargs = {"num_speakers": speakers} if speakers else {}
        output = pipeline({"waveform": torch.from_numpy(audio[None, :]), "sample_rate": sr}, **kwargs)
        turns = [
            {"start": float(turn.start), "end": float(turn.end), "speaker": speaker}
            for turn, speaker in output.speaker_diarization
        ]
    for t in turns:
        if (
            not isinstance(t, dict)
            or not isinstance(t.get("speaker"), str)
            or not t["speaker"]
            or any(
                not isinstance(t.get(k), (int, float)) or not math.isfinite(t[k]) for k in ("start", "end")
            )
            or not 0 <= t["start"] < t["end"]
        ):
            raise ValueError("Ungültiger Sprecher-Zeitbereich")
    labels = {}
    for turn in sorted(turns, key=lambda t: t["start"]):
        labels.setdefault(turn["speaker"], f"S{len(labels) + 1}")
    return [{**t, "speaker": labels[t["speaker"]]} for t in sorted(turns, key=lambda t: t["start"])]


def assign_segments(words, turns, duration):
    """Wörter den überlappenden Stimmen zuordnen, bei Sprecherwechsel/Satzende teilen."""
    segments, current = [], []
    for original in words:
        w = dict(original)
        if not 0 <= w["start"] < w["end"] <= duration + 0.05:
            raise ValueError("Whisper-Zeitstempel ausserhalb der Datei")
        candidates = [
            (max(0.0, min(w["end"], t["end"]) - max(w["start"], t["start"])), t["speaker"])
            for t in turns
            if t["start"] < w["end"] and t["end"] > w["start"]
        ]
        speaker = max(candidates, key=lambda pair: pair[0])[1] if candidates else "Unbekannt"
        w["speaker"] = speaker
        if current and (
            current[-1]["speaker"] != speaker
            or w["start"] - current[-1]["end"] > 1.2
            or current[-1]["word"].endswith((".", "!", "?", "…"))
            or w["end"] - current[0]["start"] > 25
        ):
            segments.append(make_segment(current, len(segments)))
            current = []
        current.append(w)
    if current:
        segments.append(make_segment(current, len(segments)))
    return segments


def make_segment(words, identifier):
    return {
        "id": identifier,
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "speaker": words[0]["speaker"],
        "text": " ".join(w["word"] for w in words),
        "words": words,
    }
