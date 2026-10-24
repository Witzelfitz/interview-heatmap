import json

import pytest

from pipeline.analyze import compact_overview
from pipeline.ollama import Ollama, cloud_model, local_url


@pytest.mark.parametrize(
    "url",
    [
        "https://ollama.com",
        "http://evil.example",
        "http://localhost.evil:11434",
        "http://user:password@localhost:11434",
        "http://127.0.0.1:11434/path",
        "http://127.0.0.1:11434?x=1",
    ],
)
def test_ollama_rejects_nonlocal_destinations(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_ollama_normalizes_localhost_and_ignores_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://evil.example:8000")
    client = Ollama("http://localhost:11434/")
    assert client.url == "http://127.0.0.1:11434"
    assert not any(getattr(handler, "proxies", None) for handler in client.opener.handlers)


@pytest.mark.parametrize(
    "metadata", [{"name": "model:cloud"}, {"remote_host": "https://ollama.com"}, {"remote_model": "remote"}]
)
def test_cloud_models_are_never_sent_interview_text(metadata, monkeypatch):
    client = Ollama()
    calls = []

    def api(path, body=None):
        calls.append(path)
        if path == "/api/tags":
            return {"models": [{"name": "local:latest", "digest": "abc", "capabilities": ["completion"]}]}
        return {"capabilities": ["completion"], **metadata}

    monkeypatch.setattr(client, "api", api)
    assert cloud_model(metadata)
    if metadata.get("name"):
        with pytest.raises(ValueError):
            client.inspect(metadata["name"])
    else:
        with pytest.raises(ValueError):
            client.inspect("local:latest")
    assert "/api/chat" not in calls


def test_structured_chat_uses_schema_context_and_supported_thinking(monkeypatch):
    client = Ollama()
    captured = []
    schema = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}

    def api(path, body):
        captured.append(body)
        return {"done": True, "done_reason": "stop", "message": {"content": '{"status":"ok"}'}}

    monkeypatch.setattr(client, "api", api)
    result = client.chat(
        "local", schema, "Ein lokales Interview", 100, 8192, {"thinking": {"values": ["low", "medium"]}}
    )
    assert result == {"status": "ok"}
    assert captured[0]["format"] == schema and captured[0]["think"] == "low"
    assert captured[0]["options"]["num_ctx"] == 8192 and not captured[0]["stream"]
    with pytest.raises(ValueError, match="Kontextbudget"):
        client.chat("local", schema, "Sehr lang " * 10000, 100, 8192, {})
    assert len(captured) == 1


def test_long_overview_preserves_every_score_and_section(segments, config):
    extended = []
    for i in range(16):
        for original in segments:
            row = {
                **original,
                "id": len(extended),
                "start": original["start"] + i * 384,
                "end": original["end"] + i * 384,
            }
            extended.append(row)
    scores = [{"segment_id": s["id"], "heat": s["id"] % 10} for s in extended]
    sections = [
        {
            "start_segment_id": i,
            "end_segment_id": min(i + 29, len(extended) - 1),
            "summary": "Zusammenfassung des Abschnitts.",
        }
        for i in range(0, len(extended), 30)
    ]
    result = compact_overview(extended, scores, sections, config["analysis"])
    assert len(result["segment_scores"]) == len(extended)
    assert result["section_summaries"] == sections
    assert len(result["key_passages"]) <= 40
    assert "transcript" not in result  # Gesamtkontext bleibt absichtlich hierarchisch.
    assert len(json.dumps(result).encode()) < config["analysis"]["ollama_context"] * 2


def test_ollama_analysis_has_distinct_cache_and_needs_no_cloud_key(segments, config, tmp_path, monkeypatch):
    from pipeline import analyze as analysis

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        Ollama, "inspect", lambda *_: {"digest": "local-weight-hash", "capabilities": ["completion"]}
    )
    seen = []

    def chat(self, model, schema, prompt, *_):
        seen.append(schema)
        if schema is analysis.SEGMENT_SCHEMA:
            payload = json.loads(prompt[prompt.index("[") :])
            return {
                "summary": "Ein lokaler Abschnitt.",
                "segments": [
                    {
                        "segment_id": s["id"],
                        "heat": 7,
                        "emotion": "berührt",
                        "tags": [],
                        "quotable": True,
                        "quote": s["text"],
                        "reason": "Test",
                    }
                    for s in payload
                ],
            }
        return {
            "summary": "Ein Satz. Noch ein Satz. Der Abschluss.",
            "chapters": [{"title": "Kapitel", "start_segment_id": 0, "end_segment_id": 47}],
            "phases": [],
            "highlights": [],
            "edit_recommendations": {"hooks": [], "clips": []},
        }

    monkeypatch.setattr(Ollama, "chat", chat)
    result = analysis.analyze(segments, config["analysis"], tmp_path, "ollama")
    assert result["mode"] == "ollama" and result["model_digest"] == "local-weight-hash"
    assert result["global_input"] == "section_summaries_and_all_scores"
    count = len(seen)
    analysis.analyze(segments, config["analysis"], tmp_path, "ollama")
    assert len(seen) == count
