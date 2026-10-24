import http.client
import json
import threading
from urllib.parse import urlencode

import pytest

from heatmap import ROOT
from server import Jobs, LocalServer


@pytest.fixture
def app(tmp_path, monkeypatch):
    jobs = Jobs(tmp_path / "uploads", ROOT / "config.yaml")
    queued = []

    def submit(job_id, credentials):
        queued.append((job_id, credentials))
        jobs.update(job_id, state="queued")

    monkeypatch.setattr(jobs, "submit", submit)
    server = LocalServer(("127.0.0.1", 0), jobs, max_upload=1024)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        values = {"Origin": f"http://127.0.0.1:{server.server_port}", "X-CSRF-Token": server.csrf}
        values.update(headers or {})
        connection.request(method, path, body=body, headers=values)
        response = connection.getresponse()
        status, fields, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, fields, data

    yield jobs, server, request, queued
    server.shutdown()
    server.server_close()
    jobs.pool.shutdown()
    thread.join(timeout=5)


def post_path(filename="aufnahme.wav", **options):
    return "/api/jobs?" + urlencode(
        {"filename": filename, "speaker_mode": "single", "model": "tiny", "llm": "local", **options}
    )


def test_upload_is_isolated_streamed_and_secrets_are_not_persisted(app):
    jobs, _, request, queued = app
    status, _, data = request(
        "POST", post_path("../../aufnahme.wav"), b"RIFF-test", {"X-OpenAI-Key": "sk_test-secret"}
    )
    assert status == 202
    record = json.loads(data)
    assert record["filename"] == "aufnahme.wav" and record["upload_complete"]
    folder = jobs.directory / record["id"]
    assert (folder / "input" / "aufnahme.wav").read_bytes() == b"RIFF-test"
    assert queued == [(record["id"], {"OPENAI_API_KEY": "sk_test-secret"})]
    assert "sk_test-secret" not in (folder / "job.json").read_text()
    assert "sk_test-secret" not in request("GET", "/api/jobs")[2].decode()


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://untrusted.example"}, {"X-CSRF-Token": "wrong"}, {"Host": "untrusted.example:8767"}],
)
def test_cross_origin_and_rebinding_cannot_start_jobs(app, headers):
    jobs, _, request, queued = app
    assert request("POST", post_path(), b"private", headers)[0] == 403
    assert not queued and not jobs.records


def test_large_and_unsupported_uploads_are_rejected(app):
    jobs, _, request, queued = app
    assert request("POST", post_path(), b"x" * 1025)[0] == 400
    assert request("POST", post_path("attack.html"), b"<script>")[0] == 400
    assert not queued and not jobs.records


def test_automatic_diarization_requires_local_backend_before_upload(app, monkeypatch):
    jobs, _, request, _ = app
    monkeypatch.setattr(
        jobs,
        "capabilities",
        lambda: {"ffmpeg": True, "diarization": True, "local_diarization_model": False},
    )
    status, _, data = request("POST", post_path(speaker_mode="auto"), b"private")
    assert status == 400 and "noscribe" in json.loads(data)["error"]
    assert not jobs.records


def test_automatic_diarization_starts_without_account_even_before_download(app, monkeypatch):
    jobs, _, request, queued = app
    monkeypatch.setattr(
        jobs,
        "capabilities",
        lambda: {
            "ffmpeg": True,
            "diarization": True,
            "local_diarization_model": True,
            "diarization_models_ready": False,
            "diarization_backend": "noscribe",
        },
    )
    status, _, data = request("POST", post_path(speaker_mode="auto"), b"private")
    assert status == 202 and len(queued) == 1
    assert queued[0][1] == {}  # Kein HF-Token als implizite Voraussetzung.
    assert json.loads(data)["options"]["speaker_mode"] == "auto"


def test_report_access_blocks_private_files_and_supports_media_ranges(app):
    jobs, _, request, _ = app
    job_id, _ = jobs.create("recording.wav", {})
    root = jobs.directory / job_id / "output"
    (root / "audio.wav").write_bytes(bytes(range(100)))
    (root / "cache").mkdir()
    (root / "cache" / "private.json").write_text("private")
    status, headers, data = request("GET", f"/jobs/{job_id}/audio.wav", headers={"Range": "bytes=20-39"})
    assert status == 206 and headers["Content-Range"] == "bytes 20-39/100" and data == bytes(range(20, 40))
    assert request("GET", f"/jobs/{job_id}/../job.json")[0] == 404
    assert request("GET", f"/jobs/{job_id}/cache/private.json")[0] == 404
    assert request("GET", f"/jobs/{job_id}/audio.wav", headers={"Range": "bytes=200-"})[0] == 416


def test_walkthrough_and_pdf_routes_are_read_only_and_explicit(app):
    _, _, request, _ = app
    status, _, data = request("GET", "/vorstellung/")
    assert status == 200 and b"Schnittplatz" in data
    status, headers, data = request("GET", "/vorstellung/vorstellung.pdf")
    assert status == 200 and data.startswith(b"%PDF-")
    assert headers["Content-Type"] == "application/pdf"
    assert request("GET", "/vorstellung/../../config.yaml")[0] == 404


def test_restart_marks_interrupted_job_failed_and_retains_upload(app):
    jobs, _, request, _ = app
    record = json.loads(request("POST", post_path(), b"audio")[2])
    restarted = Jobs(jobs.directory, ROOT / "config.yaml")
    try:
        state = restarted.get(record["id"])
        assert state["state"] == "failed" and state["upload_complete"]
        assert "erneut" in state["error"]
    finally:
        restarted.pool.shutdown()


def test_retry_reuses_upload_and_rejects_incomplete_data(app):
    jobs, _, request, queued = app
    record = json.loads(request("POST", post_path(), b"audio")[2])
    job_id = record["id"]
    jobs.update(job_id, state="failed")
    path = f"/api/jobs/{job_id}/retry?speaker_mode=single&model=tiny&llm=local"
    assert request("POST", path, b"")[0] == 202
    assert len(queued) == 2
    assert request("POST", path, b"")[0] == 400
    assert jobs.get(job_id)["state"] == "queued"
    assert request("POST", f"/api/jobs/{'f' * 32}/retry?speaker_mode=single&llm=local", b"")[0] == 400
    jobs.update(job_id, state="failed", upload_complete=False)
    assert request("POST", path, b"")[0] == 400


def test_worker_reports_cli_failure_and_removes_keys(tmp_path, monkeypatch):
    from server import subprocess

    jobs = Jobs(tmp_path, ROOT / "config.yaml")
    options = {
        "lang": "de",
        "model": "tiny",
        "speaker_mode": "single",
        "llm": "local",
        "remote": False,
        "render": False,
    }
    job_id, source = jobs.create("test.wav", options)
    source.write_bytes(b"invalid")
    credentials = {"HF_TOKEN": "hf_do-not-log"}

    class FailedProcess:
        stdout = ("INFO · 2/7 Transkription\n", "ERROR · hf_do-not-log: Modell fehlt\n")

        def __init__(self, command, **kwargs):
            assert kwargs["env"]["HF_TOKEN"] == "hf_do-not-log"
            assert "--single-speaker" in command and "--remote" not in command

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def wait(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", FailedProcess)
    try:
        jobs.run(job_id, credentials)
        assert jobs.get(job_id)["state"] == "failed"
        assert jobs.get(job_id)["stage"] == 2
        assert "hf_do-not-log" not in (tmp_path / job_id / "pipeline.log").read_text()
        assert "hf_do-not-log" not in (tmp_path / job_id / "job.json").read_text()
        assert credentials == {}
    finally:
        jobs.pool.shutdown()
