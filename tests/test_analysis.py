import json
import sys
from types import SimpleNamespace

import pytest

from pipeline import analyze as analysis_module
from pipeline.cuts import proposals


def test_claude_chunk_merge_global_context_and_exact_quotes(segments, config, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **_: object()))
    calls = []

    def fake_request(client, model, schema, prompt, tokens):
        calls.append(schema)
        if schema is analysis_module.SEGMENT_SCHEMA:
            payload = json.loads(prompt[prompt.index("[") :])
            return {
                "summary": "Abschnitt.",
                "segments": [
                    {
                        "segment_id": s["id"],
                        "heat": 8,
                        "emotion": "berührt",
                        "tags": ["persönliche Geschichte"],
                        "quotable": True,
                        "quote": "Frei erfundener Satz" if s["id"] == 0 else s["text"],
                        "reason": "Begründung",
                    }
                    for s in payload
                ],
            }
        payload = json.loads(prompt[prompt.index('{"section_summaries"') :])
        assert len(payload["transcript"]) == len(segments)
        return {
            "summary": "Satz eins. Satz zwei. Satz drei.",
            "chapters": [{"title": "Ein Kapitel", "start_segment_id": 0, "end_segment_id": 47}],
            "phases": [{"phase": "Exposition", "start_segment_id": 0, "end_segment_id": 47}],
            "highlights": [{"segment_id": 3, "title": "Moment", "reason": "Begründung"}],
            "edit_recommendations": {
                "hooks": [
                    {
                        "start_segment_id": 3,
                        "end_segment_id": 3,
                        "title": "Eine offene Frage",
                        "reason": "Weckt Neugier",
                    }
                ],
                "clips": [
                    {
                        "start_segment_id": 3,
                        "end_segment_id": 6,
                        "title": "Vom Zweifel zum Vertrauen",
                        "reason": "Klare Entwicklung",
                    }
                ],
            },
        }

    monkeypatch.setattr(analysis_module, "request_claude", fake_request)
    result = analysis_module.analyze(segments, config["analysis"], tmp_path, "claude")
    assert len(result["segments"]) == len(segments)
    assert not result["segments"][0]["quotable"]
    assert all(row["quote"] in segments[row["segment_id"]]["text"] for row in result["segments"])
    assert calls.count(analysis_module.GLOBAL_SCHEMA) == 1
    count = len(calls)
    analysis_module.analyze(segments, config["analysis"], tmp_path, "claude")
    assert len(calls) == count  # API wird bei identischem Transkript nicht erneut aufgerufen.


def test_editorial_recommendations_use_real_sentence_boundaries(analyzed, config):
    analyzed["analysis"]["edit_recommendations"] = {
        "hooks": [
            {"start_segment_id": 3, "end_segment_id": 3, "title": "Redaktioneller Hook", "reason": "Frage"}
        ],
        "clips": [
            {"start_segment_id": 3, "end_segment_id": 6, "title": "Redaktioneller Clip", "reason": "Pointe"}
        ],
    }
    cuts = proposals(analyzed["scored"], analyzed["analysis"], 384, config["cuts"])
    assert cuts["hook"]["title"] == "Redaktioneller Hook"
    assert cuts["clips"][0]["title"] == "Redaktioneller Clip"
    assert cuts["clips"][0]["start"] < analyzed["scored"]["segments"][3]["start"]
    assert cuts["clips"][0]["end"] > analyzed["scored"]["segments"][6]["end"]


def test_remote_transcription_keeps_offsets_and_never_used_by_default(tmp_path, monkeypatch):
    import wave

    from pipeline.transcribe import remote_transcribe

    audio = tmp_path / "long.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000 * 601)
    sizes = []

    def create(**kwargs):
        sizes.append(len(kwargs["file"].read()))
        assert kwargs["timestamp_granularities"] == ["word", "segment"]
        return SimpleNamespace(text="Hallo.", words=[SimpleNamespace(word="Hallo.", start=0.1, end=0.5)])

    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(
            OpenAI=lambda **_: SimpleNamespace(
                audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
            )
        ),
    )
    result = remote_transcribe(audio, "de")
    assert len(sizes) == 2 and max(sizes) < 25 * 1024**2
    assert result["words"][1]["start"] == pytest.approx(600.1)
