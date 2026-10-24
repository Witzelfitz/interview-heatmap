#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

# Vor jeglichem ML-Import: auch lokale Diarisierungs-Telemetrie deaktivieren.
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

ROOT = Path(__file__).resolve().parent
if not (ROOT / "config.yaml").exists():
    ROOT = Path(sys.prefix) / "share" / "interview-heatmap"
log = logging.getLogger("heatmap")


def parser():
    p = argparse.ArgumentParser(
        description="Interview Heatmap & Schnitt-Advisor – Audio bleibt standardmässig lokal."
    )
    p.add_argument("media", type=Path)
    p.add_argument("--out", type=Path, default=Path("output"))
    p.add_argument("--lang", default="de", help="Whisper-Sprachcode, z.B. de")
    p.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--model", help="auto, large-v3, medium, small, tiny oder lokaler Modellpfad")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"])
    p.add_argument("--compute-type", help="z.B. int8 oder float16")
    p.add_argument("--remote", action="store_true", help="Explizit Audio an OpenAI Whisper senden")
    p.add_argument(
        "--llm",
        choices=["ollama", "local", "claude"],
        default="ollama",
        help="ollama: lokales LLM; local: Heuristik; claude: Text an Anthropic",
    )
    p.add_argument("--ollama-model", help="Lokal installiertes Ollama-Modell")
    p.add_argument(
        "--offline",
        action="store_true",
        help="Nur lokale Modelle; keine Downloads/Cloud-Aufrufe (Ollama auf Loopback erlaubt)",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--single-speaker", action="store_true", help="Nur für Aufnahmen mit genau einer Stimme"
    )
    group.add_argument(
        "--diarization-file", type=Path, help="Vorhandene echte Sprecherbereiche als JSON importieren"
    )
    p.add_argument("--speakers", type=int, help="Bekannte Anzahl Stimmen für pyannote")
    p.add_argument("--diarization-model", help="noscribe (ohne Konto) oder lokales Modellverzeichnis")
    p.add_argument(
        "--skip-transcribe", action="store_true", help="Passenden Transkript-Cache zwingend wiederverwenden"
    )
    p.add_argument(
        "--transcribe-only", action="store_true", help="Nach Audio, Transkript, SRT und TXT stoppen"
    )
    p.add_argument("--copy-media", action="store_true", help="Originaldatei zum Report kopieren")
    p.add_argument("--render-clips", action="store_true", help="Hook/Social Clips mit ffmpeg rendern")
    p.add_argument(
        "--source-timecode", default="00:00:00:00", help="EDL-Quellstart HH:MM:SS:FF (non-drop-frame)"
    )
    return p


def load_config(path):
    import yaml

    default = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if path.resolve() != (ROOT / "config.yaml").resolve():
        custom = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section, fields in custom.items():
            if section not in default or not isinstance(fields, dict):
                raise ValueError(f"Unbekannter/ungültiger Config-Bereich: {section}")
            for key, value in fields.items():
                if key not in default[section]:
                    raise ValueError(f"Unbekannte Config-Option: {section}.{key}")
                default[section][key] = value
    a, s, c = default["analysis"], default["scoring"], default["cuts"]
    if not a["chunk_seconds"] > a["overlap_seconds"] >= 0:
        raise ValueError("chunk_seconds muss grösser als overlap_seconds sein")
    from pipeline.ollama import local_url

    local_url(a["ollama_url"])
    if not 0 < a["ollama_max_tokens"] < a["ollama_context"] - 2048 or a["ollama_timeout"] <= 0:
        raise ValueError("Ungültiges Ollama-Kontext-/Tokenbudget oder Zeitlimit")
    if min(s["llm_weight"], s["audio_weight"]) < 0 or abs(s["llm_weight"] + s["audio_weight"] - 1) > 1e-6:
        raise ValueError("Heat-Gewichte müssen nichtnegativ sein und zusammen 1 ergeben")
    if s["smoothing_seconds"] <= 0 or s["peak_distance_seconds"] <= 0 or s["peak_prominence"] < 0:
        raise ValueError("Ungültige Glättungs-/Peak-Konfiguration")
    for prefix in ("hook", "clip"):
        if not 0 < c[f"{prefix}_min_seconds"] <= c[f"{prefix}_max_seconds"]:
            raise ValueError(f"Ungültige {prefix}-Dauer")
    if (
        c["edl_fps"] not in (24, 25, 30)
        or not 3 <= c["clip_count"] <= 8
        or not 0 <= c["retention_threshold"] <= 1
        or c["retention_seconds"] <= 0
        or c["pause_padding_seconds"] < 0
        or not c["short_minutes"]
        or any(not isinstance(m, int) or m <= 0 for m in c["short_minutes"])
    ):
        raise ValueError("Ungültige Schnitt-Konfiguration")
    return default


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s · %(message)s")
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        if args.offline and (args.remote or args.llm == "claude"):
            raise ValueError("--offline kann nicht mit --remote oder --llm claude kombiniert werden")
        if args.speakers is not None and (args.speakers < 1 or args.single_speaker or args.diarization_file):
            raise ValueError("--speakers benötigt pyannote und eine positive Anzahl")
        if not args.media.is_file():
            raise ValueError(f"Mediendatei fehlt: {args.media}")
        if args.remote and not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("--remote benötigt OPENAI_API_KEY")
        if args.llm == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError("--llm claude benötigt ANTHROPIC_API_KEY")
        config = load_config(args.config)
        if args.ollama_model:
            config["analysis"]["ollama_model"] = args.ollama_model
        from pipeline.audio import features, prepare
        from pipeline.common import (
            cached,
            digest,
            export_transcript,
            file_hash,
            validate_transcript,
            write_json,
        )
        from pipeline.transcribe import assign_segments, diarize, local_transcribe, remote_transcribe

        source, out = args.media.resolve(), args.out.resolve()
        if source.parent == out and source.name in {
            "audio.wav",
            "transcript.json",
            "report.html",
            "report.json",
        }:
            raise ValueError(
                "Die Quelldatei würde durch eine Ausgabedatei überschrieben; anderen --out wählen"
            )
        out.mkdir(parents=True, exist_ok=True)
        cache = out / "cache"
        cache.mkdir(exist_ok=True)
        options = config["transcription"].copy()
        for flag, key in (
            (args.model, "model"),
            (args.device, "device"),
            (args.compute_type, "compute_type"),
            (args.diarization_model, "diarization_model"),
        ):
            if flag:
                options[key] = flag
        if options["diarization_model"] == "noscribe":
            from pipeline.models import REVISION

            options["diarization_revision"] = REVISION
        log.info("1/7 Audio vorbereiten: %s", source.name)
        wav, metadata = prepare(source, out)
        transcription_key = digest(
            {
                "source": metadata["sha256"],
                "language": args.lang,
                "remote": args.remote,
                "options": options,
                "single": args.single_speaker,
                "speakers": args.speakers,
                "turns": file_hash(args.diarization_file) if args.diarization_file else None,
                "pipeline_version": 1,
            }
        )
        path = out / "transcript.json"
        transcript = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        matches = transcript and transcript.get("transcription_key") == transcription_key
        if args.skip_transcribe and not matches:
            raise ValueError(
                "Kein passender Transkript-Cache. Quelle, Sprache, Modell und Sprecheroptionen müssen übereinstimmen."
            )
        if matches:
            log.info("2/7 Passenden Transkript-Cache verwenden")
        else:
            log.info("2/7 Transkription und lokale Sprecher-Zuordnung")
            raw_key = digest(
                {
                    "source": metadata["sha256"],
                    "language": args.lang,
                    "remote": args.remote,
                    "model": options["model"],
                    "device": options["device"],
                    "compute": options["compute_type"],
                }
            )
            raw = cached(
                cache / f"whisper-{raw_key}.json",
                raw_key,
                lambda: (
                    remote_transcribe(wav, args.lang)
                    if args.remote
                    else local_transcribe(
                        wav,
                        args.lang,
                        options["model"],
                        options["device"],
                        options["compute_type"],
                        args.offline,
                    )
                ),
            )
            if args.single_speaker:
                turns = [{"start": 0.0, "end": metadata["duration"], "speaker": "S1"}]
                diarization_mode = "single_speaker_explicit"
            else:
                turn_key = digest(
                    {
                        "source": metadata["sha256"],
                        "model": options["diarization_model"],
                        "revision": options.get("diarization_revision"),
                        "speakers": args.speakers,
                        "file": file_hash(args.diarization_file) if args.diarization_file else None,
                    }
                )
                turns = cached(
                    cache / f"diarization-{turn_key}.json",
                    turn_key,
                    lambda: diarize(
                        wav, options["diarization_model"], args.speakers, args.diarization_file, args.offline
                    ),
                )
                diarization_mode = (
                    "imported_turns"
                    if args.diarization_file
                    else "noscribe_local"
                    if options["diarization_model"] == "noscribe"
                    else "pyannote_local"
                )
            transcript = {
                "transcription_key": transcription_key,
                "metadata": metadata,
                "turns": turns,
                "provenance": {k: v for k, v in raw.items() if k != "words"},
                "diarization": diarization_mode,
                "segments": assign_segments(raw["words"], turns, metadata["duration"]),
            }
        transcript["metadata"] = metadata
        validate_transcript(transcript["segments"], metadata["duration"])
        if not transcript["segments"]:
            raise ValueError("Keine Sprache erkannt. Aufnahme und Sprachwahl prüfen.")
        export_transcript(transcript, out)
        if args.transcribe_only:
            log.info("Fertig: %s", out / "transcript.json")
            return 0
        from pipeline.analyze import analyze
        from pipeline.cuts import export_edls, parse_timecode, proposals, render_script
        from pipeline.report import build_report
        from pipeline.scoring import score

        parse_timecode(args.source_timecode, config["cuts"]["edl_fps"])
        log.info("3/7 Audio-Merkmale pro Sprecher normalisieren")
        feature_key = digest(
            {
                "source": metadata["sha256"],
                "segments": transcript["segments"],
                "turns": transcript["turns"],
                "features_version": 2,
            }
        )
        audio_features = cached(
            cache / "features.json",
            feature_key,
            lambda: features(wav, transcript["segments"], transcript["turns"]),
        )
        write_json(out / "audio_features.json", audio_features)
        log.info("4/7 Inhalt und Dramaturgie: %s", args.llm)
        analysis = analyze(transcript["segments"], config["analysis"], cache, args.llm)
        write_json(out / "analysis.json", analysis)
        log.info("5/7 Heat-Kurve und Peaks")
        scored = score(
            transcript["segments"], audio_features, analysis, metadata["duration"], config["scoring"]
        )
        write_json(out / "heatmap.json", scored)
        log.info("6/7 Schnittvorschläge und EDL")
        cuts = proposals(scored, analysis, metadata["duration"], config["cuts"])
        write_json(out / "cuts.json", cuts)
        exports = export_edls(cuts, metadata, scored["segments"], out, args.source_timecode)
        render_script(
            cuts, scored["segments"], source, out, args.render_clips, metadata["media_type"] == "video"
        )
        media_name = source.name
        # audio.wav ist sowieso beim Report und direkt abspielbar; Video optional danebenlegen.
        if args.copy_media and source.parent != out:
            if media_name == "audio.wav":
                media_name = "original-audio.wav"
            shutil.copy2(source, out / media_name)
        metadata.update(
            {
                "media_file": media_name,
                "audio_file": "audio.wav",
                "language": args.lang,
                "created_at": datetime.now(UTC).isoformat(),
                "audio_remote": args.remote,
                "text_remote": args.llm == "claude",
                "diarization": transcript["diarization"],
                "edl_source_timecode": args.source_timecode,
            }
        )
        data = {
            "metadata": metadata,
            "analysis": analysis,
            "scored": scored,
            "cuts": cuts,
            "transcript": transcript,
            "exports": {**exports, "transcript.srt": (out / "transcript.srt").read_text(encoding="utf-8")},
        }
        write_json(out / "report.json", data)
        log.info("7/7 Eigenständigen HTML-Report schreiben")
        build_report(data, ROOT / "templates" / "report.html", out / "report.html")
        log.info("Fertig: %s", out / "report.html")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
