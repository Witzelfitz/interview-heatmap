"""Lokale Upload-Oberfläche; führt jeden Auftrag in einem isolierten CLI-Prozess aus."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from heatmap import ROOT, load_config
from pipeline.common import write_json
from pipeline.models import models_ready
from pipeline.ollama import Ollama

MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".aiff",
    ".aif",
}
SECRET_HEADERS = {
    "ANTHROPIC_API_KEY": "X-Anthropic-Key",
    "OPENAI_API_KEY": "X-OpenAI-Key",
}
STAGES = [
    "Audio vorbereiten",
    "Transkription & Sprecher",
    "Audio-Merkmale",
    "Inhalt & Dramaturgie",
    "Heat-Kurve & Peaks",
    "Schnittvorschläge & Export",
    "Report erstellen",
]


def module_available(name):
    try:
        return find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


class Jobs:
    def __init__(self, directory: Path, config: Path, demo: Path | None = None):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config = config.resolve()
        self.demo = demo.resolve() if demo and demo.is_dir() else None
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="interview")
        self.records = {}
        for path in self.directory.glob("*/job.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
                    continue
                if record["state"] in {"queued", "running", "uploading"}:
                    record.update(
                        state="failed",
                        error="Der Server wurde während des Auftrags beendet. Du kannst die Analyse erneut starten.",
                    )
                    write_json(path, record)
                self.records[record["id"]] = record
            except (OSError, ValueError, KeyError):
                continue

    def capabilities(self):
        config = load_config(self.config)
        model = config["transcription"]["diarization_model"]
        try:
            models = Ollama(config["analysis"]["ollama_url"], timeout=1).models()
        except (OSError, ValueError, RuntimeError):
            models = []
        model_names = [m["name"] for m in models]
        preferred = config["analysis"]["ollama_model"]
        return {
            "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "diarization": module_available("pyannote.audio"),
            "local_diarization_model": model == "noscribe" or Path(model).is_dir(),
            "diarization_models_ready": models_ready() if model == "noscribe" else Path(model).is_dir(),
            "diarization_backend": "noscribe" if model == "noscribe" else "local",
            "claude": module_available("anthropic"),
            "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "remote": module_available("openai"),
            "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
            "ollama": bool(models),
            "ollama_models": [{"name": m["name"], "size": m.get("size", 0)} for m in models],
            "ollama_model": preferred
            if preferred in model_names
            else model_names[0]
            if model_names
            else preferred,
            "demo_url": "/demo/report.html" if self.demo else None,
            "stages": STAGES,
        }

    def options(self, query, headers):
        def value(name, default):
            return query.get(name, [default])[0]

        options = {
            "lang": value("lang", "de"),
            "model": value("model", "auto"),
            "speaker_mode": value("speaker_mode", "auto"),
            "llm": value("llm", "ollama"),
            "ollama_model": value("ollama_model", ""),
            "remote": value("remote", "false") == "true",
            "render": value("render", "true") == "true",
        }
        if (
            options["lang"] not in {"de", "en", "fr", "it"}
            or options["model"] not in {"auto", "large-v3", "medium", "small", "tiny"}
            or options["speaker_mode"] not in {"auto", "single"}
            or options["llm"] not in {"ollama", "local", "claude"}
        ):
            raise ValueError("Ungültige Analyse-Einstellungen")
        # Nur Prozessumgebung, niemals Job-JSON, URL oder Logdatei.
        credentials = {key: headers.get(header, "").strip() for key, header in SECRET_HEADERS.items()}
        cap = self.capabilities()
        if options["llm"] == "ollama":
            if not cap["ollama"]:
                raise ValueError(
                    "Ollama starten und ein Chat-Modell lokal installieren (z.B. ollama pull gpt-oss:20b)."
                )
            options["ollama_model"] = options["ollama_model"] or cap["ollama_model"]
            Ollama(load_config(self.config)["analysis"]["ollama_url"], timeout=10).inspect(
                options["ollama_model"]
            )
        if not cap["ffmpeg"]:
            raise ValueError("ffmpeg/ffprobe fehlt. Bitte gemäss README installieren.")
        if options["speaker_mode"] == "auto":
            if not cap["diarization"]:
                raise ValueError("Automatische Sprechererkennung benötigt pip install '.[diarization]'.")
            if not cap["local_diarization_model"]:
                raise ValueError(
                    "Für die Sprechererkennung in config.yaml diarization_model: noscribe oder ein lokales Modellverzeichnis einstellen."
                )
        if options["llm"] == "claude" and (
            not cap["claude"] or not (credentials["ANTHROPIC_API_KEY"] or cap["anthropic_key"])
        ):
            raise ValueError("Claude benötigt das Paket .[claude] und einen Anthropic-API-Schlüssel.")
        if options["remote"] and (
            not cap["remote"] or not (credentials["OPENAI_API_KEY"] or cap["openai_key"])
        ):
            raise ValueError(
                "Remote-Transkription benötigt das Paket .[remote] und einen OpenAI-API-Schlüssel."
            )
        return options, {key: value for key, value in credentials.items() if value}

    def update(self, job_id, **changes):
        with self.lock:
            self.records[job_id].update(changes, updated_at=time.time())
            write_json(self.directory / job_id / "job.json", self.records[job_id])

    def get(self, job_id):
        with self.lock:
            if job_id not in self.records:
                return None
            record = dict(self.records[job_id])
        record["report_url"] = f"/jobs/{job_id}/report.html" if record["state"] == "done" else None
        record["data_url"] = f"/jobs/{job_id}/report.json" if record["state"] == "done" else None
        return record

    def create(self, name, options):
        name = Path(name.replace("\\", "/")).name
        # Original darf keine Arbeitsdateien im Report überschreiben.
        if (
            not name
            or len(name.encode()) > 200
            or any(ord(c) < 32 for c in name)
            or Path(name).suffix.lower() not in MEDIA_EXTENSIONS
        ):
            raise ValueError("Bitte eine gültige Audio- oder Videodatei wählen (MP4, MOV, WAV, MP3, M4A …).")
        job_id = secrets.token_hex(16)
        folder = self.directory / job_id
        (folder / "input").mkdir(parents=True)
        (folder / "output").mkdir()
        record = {
            "id": job_id,
            "filename": name,
            "state": "uploading",
            "stage": 0,
            "detail": "Datei wird lokal gespeichert",
            "error": None,
            "upload_complete": False,
            "created_at": time.time(),
            "updated_at": time.time(),
            "options": options,
        }
        with self.lock:
            self.records[job_id] = record
        self.update(job_id)
        return job_id, folder / "input" / name

    def submit(self, job_id, credentials):
        self.update(job_id, state="queued", stage=0, detail="Wartet auf die lokale Verarbeitung", error=None)
        self.pool.submit(self.run, job_id, credentials)

    def run(self, job_id, credentials):
        record = self.get(job_id)
        folder = self.directory / job_id
        options = record["options"]
        command = [
            sys.executable,
            "-u",
            "-m",
            "heatmap",
            str(folder / "input" / record["filename"]),
            "--out",
            str(folder / "output"),
            "--config",
            str(self.config),
            "--lang",
            options["lang"],
            "--model",
            options["model"],
            "--llm",
            options["llm"],
        ]
        if options["speaker_mode"] == "single":
            command.append("--single-speaker")
        if options["remote"]:
            command.append("--remote")
        if options["render"]:
            command.append("--render-clips")
        if options.get("llm") == "ollama":
            command.extend(["--ollama-model", options["ollama_model"]])
        # Original liegt bereits in input; für den Player später sicher verlinken.
        env = dict(os.environ, **credentials)
        env.pop("HF_HUB_OFFLINE", None)
        env.pop("TRANSFORMERS_OFFLINE", None)
        self.update(job_id, state="running", stage=1, detail=STAGES[0])
        last_error = "Analyse fehlgeschlagen; siehe lokales Protokoll."
        try:
            with (
                (folder / "pipeline.log").open("w", encoding="utf-8") as logfile,
                subprocess.Popen(
                    command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
                ) as process,
            ):
                for line in process.stdout:
                    # Auch Bibliotheksfehler dürfen die flüchtigen Schlüssel nicht speichern.
                    for secret in credentials.values():
                        line = line.replace(secret, "[entfernt]")
                    for key in SECRET_HEADERS:
                        if os.environ.get(key):
                            line = line.replace(os.environ[key], "[entfernt]")
                    logfile.write(line)
                    logfile.flush()
                    match = re.search(r"INFO · ([1-7])/7 (.*)", line)
                    if match:
                        self.update(job_id, stage=int(match[1]), detail=match[2].strip())
                    elif any(
                        marker in line
                        for marker in ("Transkribiert bis", "Analysefenster", "Gesamtdramaturgie")
                    ):
                        self.update(job_id, detail=line.split("·", 1)[-1].strip())
                    if "ERROR" in line or "Error:" in line:
                        last_error = line.strip().removeprefix("ERROR · ")[:2000]
                code = process.wait()
            if code or not (folder / "output" / "report.html").exists():
                raise RuntimeError(last_error)
            metadata = json.loads((folder / "output" / "report.json").read_text())["metadata"]
            target = folder / "output" / metadata["media_file"]
            if not target.exists():
                try:
                    os.link(folder / "input" / record["filename"], target)
                except OSError:
                    shutil.copy2(folder / "input" / record["filename"], target)
            self.update(job_id, state="done", stage=7, detail="Analyse abgeschlossen", error=None)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self.update(job_id, state="failed", detail="Analyse angehalten", error=str(exc))
        finally:
            credentials.clear()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, jobs, max_upload=20 * 1024**3):
        self.jobs, self.max_upload = jobs, max_upload
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Keine Originaldateinamen, Schlüssel oder Interviewtexte im Serverzugriffslog.

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def valid_host(self):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        return host in {f"localhost:{port}", f"127.0.0.1:{port}"}

    def read_only(self):
        if not self.valid_host():
            return self.reply(403, {"error": "Ungültiger lokaler Host"})
        path = unquote(urlsplit(self.path).path)
        if path == "/report.html":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/":
            self.serve_file(ROOT / "templates" / "upload.html")
        elif path == "/api/status":
            self.reply(
                200,
                {
                    **self.server.jobs.capabilities(),
                    "csrf": self.server.csrf,
                    "max_upload_bytes": self.server.max_upload,
                },
            )
        elif path == "/api/jobs":
            records = [self.server.jobs.get(k) for k in self.server.jobs.records.copy()]
            self.reply(200, {"jobs": sorted(records, key=lambda r: r["created_at"], reverse=True)})
        elif re.fullmatch(r"/api/jobs/[0-9a-f]{32}", path):
            job = self.server.jobs.get(path.rsplit("/", 1)[-1])
            self.reply(200 if job else 404, job or {"error": "Auftrag nicht gefunden"})
        elif match := re.fullmatch(r"/jobs/([0-9a-f]{32})/(.+)", path):
            root = self.server.jobs.directory / match[1] / "output"
            self.artifact(root, match[2])
        elif path.startswith("/demo/") and self.server.jobs.demo:
            self.artifact(self.server.jobs.demo, path.removeprefix("/demo/"))
        else:
            self.reply(404, {"error": "Nicht gefunden"})

    def do_GET(self):
        self.read_only()

    def do_HEAD(self):
        self.read_only()

    def do_POST(self):
        expected = {
            f"http://localhost:{self.server.server_port}",
            f"http://127.0.0.1:{self.server.server_port}",
        }
        if (
            not self.valid_host()
            or self.headers.get("Origin") not in expected
            or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.csrf)
        ):
            self.close_connection = True
            return self.reply(403, {"error": "Bitte die lokale Upload-Seite neu laden."})
        url = urlsplit(self.path)
        job_id = None
        created_upload = False
        try:
            query = parse_qs(url.query)
            options, credentials = self.server.jobs.options(query, self.headers)
            if match := re.fullmatch(r"/api/jobs/([0-9a-f]{32})/retry", url.path):
                job_id = match[1]
                with self.server.jobs.lock:
                    old = self.server.jobs.get(job_id)
                    if not old or old["state"] != "failed":
                        raise ValueError("Nur fehlgeschlagene Aufträge können erneut gestartet werden.")
                    if not old.get("upload_complete"):
                        raise ValueError("Der Upload war unvollständig. Bitte die Datei erneut hochladen.")
                    self.server.jobs.update(job_id, options=options)
                    self.server.jobs.submit(job_id, credentials)
                return self.reply(202, self.server.jobs.get(job_id))
            if url.path != "/api/jobs":
                return self.reply(404, {"error": "Nicht gefunden"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= self.server.max_upload or self.headers.get("Transfer-Encoding"):
                raise ValueError("Leere oder zu grosse Datei. Maximal 20 GiB pro Upload.")
            job_id, target = self.server.jobs.create(query.get("filename", [""])[0], options)
            created_upload = True
            self.connection.settimeout(120)
            remaining = length
            with target.open("wb") as stream:
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("Upload wurde unterbrochen. Bitte Datei erneut wählen.")
                    stream.write(block)
                    remaining -= len(block)
            self.connection.settimeout(None)
            self.server.jobs.update(job_id, upload_complete=True)
            self.server.jobs.submit(job_id, credentials)
            self.reply(202, self.server.jobs.get(job_id))
        except (OSError, ValueError) as exc:
            self.close_connection = True
            if created_upload:
                self.server.jobs.update(job_id, state="failed", error=str(exc))
            self.reply(400, {"error": str(exc)})

    def artifact(self, root, relative):
        path = root / relative
        if (
            "cache" in Path(relative).parts
            or not path.resolve().is_relative_to(root.resolve())
            or path.suffix.lower() not in MEDIA_EXTENSIONS | {".html", ".json", ".srt", ".txt", ".edl"}
        ):
            return self.reply(404, {"error": "Datei nicht verfügbar"})
        self.serve_file(path)

    def serve_file(self, path):
        import mimetypes

        if not path.is_file():
            return self.reply(404, {"error": "Datei nicht gefunden"})
        size, start, end = path.stat().st_size, 0, path.stat().st_size - 1
        partial = self.headers.get("Range")
        if partial:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", partial)
            if not match or not any(match.groups()):
                return self.reply(416, {"error": "Ungültiger Bytebereich"})
            left, right = match.groups()
            if left:
                start, end = int(left), min(end, int(right)) if right else end
            else:
                start = max(0, size - int(right))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser(description="Lokale Upload-App für die vollständige Interview-Pipeline")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--data", type=Path, default=Path("output/uploads"))
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--demo", type=Path, default=ROOT / "test-output/medium")
    args = parser.parse_args()
    jobs = Jobs(args.data, args.config, args.demo)
    server = LocalServer(("127.0.0.1", args.port), jobs)
    print(f"Interview-Upload läuft: http://localhost:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        jobs.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
