import json
import math
import socket
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from heatmap import main
from pipeline.analyze import checked_score, windows
from pipeline.audio import features, overlap_duration, prepare
from pipeline.common import cached, digest, timestamp, validate_transcript
from pipeline.cuts import edl, parse_timecode, safe_frame, timecode
from pipeline.report import build_report
from pipeline.transcribe import assign_segments, diarize


def test_hosted_diarization_is_rejected_before_import_or_upload(tmp_path):
    with pytest.raises(ValueError, match="gehostete"):
        diarize(tmp_path / "private.wav", "pyannote/speaker-diarization-precision-2")


def test_imported_speaker_turns_reject_nonfinite_times(tmp_path):
    path = tmp_path / "turns.json"
    path.write_text('[{"start": 0, "end": NaN, "speaker": "guest"}]')
    with pytest.raises(ValueError):
        diarize(tmp_path / "audio.wav", "", turns_file=path)


def test_word_speaker_assignment_preserves_times_and_splits_sentence():
    words = [
        {"word": "Warum?", "start": 0.2, "end": 1.0},
        {"word": "Weil", "start": 1.5, "end": 2.0},
        {"word": "darum.", "start": 2.1, "end": 2.8},
    ]
    turns = [{"start": 0, "end": 1.1, "speaker": "S1"}, {"start": 1.2, "end": 3, "speaker": "S2"}]
    rows = assign_segments(words, turns, 3)
    assert [s["speaker"] for s in rows] == ["S1", "S2"]
    assert rows[1]["words"][1]["start"] == 2.1
    validate_transcript(rows, 3)
    assert assign_segments(words, [], 3)[0]["speaker"] == "Unbekannt"


def test_quotes_are_exact_not_fuzzy():
    s = {"id": 42, "text": "Das ist eine grosse Überraschung."}
    row = {"heat": 8, "quotable": True, "quote": "eine große Überraschung", "reason": "Test"}
    assert checked_score(row, s)["quote"] == "eine grosse Überraschung"
    assert not checked_score({**row, "quote": "eine riesige Überraschung"}, s)["quotable"]
    with pytest.raises(ValueError):
        checked_score({**row, "heat": math.nan}, s)


def test_overlapping_windows_have_no_missing_segments(segments):
    groups = list(windows(segments, 150, 20))
    ids = {s["id"] for _, group in groups for s in group}
    assert ids == {s["id"] for s in segments}
    assert sum(len(g) for _, g in groups) > len(segments)


def test_cache_invalidates_and_does_not_store_failure(tmp_path):
    path = tmp_path / "cache.json"
    assert cached(path, "a", lambda: 1) == 1
    assert cached(path, "a", lambda: 2) == 1
    assert cached(path, "b", lambda: 2) == 2

    def fail():
        raise RuntimeError("test")

    with pytest.raises(RuntimeError):
        cached(path, "c", fail)
    assert json.loads(path.read_text())["key"] == "b"


def test_audio_normalization_is_per_speaker(tmp_path):
    sr = 16000
    t = np.arange(sr) / sr
    wave = np.concatenate([np.sin(2 * np.pi * 180 * t) * amp for amp in [0.01, 0.02, 0.1, 0.2]])
    path = tmp_path / "voices.wav"
    sf.write(path, wave, sr)
    rows = [
        {"id": i, "start": i, "end": i + 1, "speaker": "S1" if i < 2 else "S2", "words": [1, 2]}
        for i in range(4)
    ]
    result = features(path, rows, [])
    assert result[0]["z"]["rms"] == pytest.approx(result[2]["z"]["rms"], abs=0.001)
    assert result[1]["audio_score"] == pytest.approx(result[3]["audio_score"], abs=0.001)
    assert all(r["laughter"] is None for r in result)
    assert (
        overlap_duration(0, 5, [{"start": 0, "end": 3}, {"start": 2, "end": 4}, {"start": 2.5, "end": 5}])
        == 2
    )


def test_ffmpeg_extraction_and_cache(tmp_path):
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(44100 * 2), 44100)
    out = tmp_path / "out"
    out.mkdir()
    wav, metadata = prepare(source, out)
    assert sf.info(wav).samplerate == 16000
    assert metadata["duration"] == 2
    mtime = wav.stat().st_mtime_ns
    prepare(source, out)
    assert wav.stat().st_mtime_ns == mtime
    # Beschädigte WAV darf nicht blind als gültiger Cache übernommen werden.
    wav.write_bytes(b"broken")
    prepare(source, out)
    assert sf.info(wav).duration == 2


def test_cuts_are_complete_and_never_inside_word(analyzed):
    cuts = analyzed["cuts"]
    assert cuts["hook"] and 5 <= cuts["hook"]["duration"] <= 15
    assert 3 <= len(cuts["clips"]) <= 8
    selected = [cuts["hook"], *cuts["clips"], *cuts["reductions"]]
    words = [w for s in analyzed["scored"]["segments"] for w in s["words"]]
    for version in cuts["short_versions"].values():
        assert version["duration"] <= version["target_seconds"]
        assert version["cuts"] == sorted(version["cuts"], key=lambda c: c["start"])
        selected.extend(version["cuts"])
    for cut in selected:
        assert cut["subtitle_text"].endswith((".", "?", "!"))
        for edge in (cut["start"], cut["end"]):
            assert not any(w["start"] < edge < w["end"] for w in words)
    for c in cuts["clips"]:
        assert 15 <= c["duration"] <= 60


@pytest.mark.parametrize("fps", [24, 25, 30])
def test_edl_frames_and_record_continuity(analyzed, fps):
    words = [w for s in analyzed["scored"]["segments"] for w in s["words"]]
    text = edl(analyzed["cuts"]["clips"], "file\nEVIL.mp4", fps, words, "02:00:00:00")
    lines = [line.split() for line in text.splitlines() if line[:3].isdigit()]
    previous = 3600 * fps
    for line in lines:
        a, b, c, d = [parse_timecode(v, fps) for v in line[-4:]]
        assert c == previous
        assert d - c == b - a > 0
        previous = d
    assert "\nEVIL" not in text
    for edge in (1.12, 7.08, 21.43):
        for direction in (-1, 1):
            point = safe_frame(edge, fps, words, direction) / fps
            assert not any(w["start"] + 1e-8 < point < w["end"] - 1e-8 for w in words)
    assert parse_timecode(timecode(123456, fps), fps) == 123456


def test_report_escapes_script_termination(analyzed, tmp_path):
    evil = '</script><script>alert("interview")</script>'
    analyzed["metadata"]["filename"] = evil
    destination = tmp_path / "report.html"
    build_report(analyzed, Path(__file__).parents[1] / "templates/report.html", destination)
    html = destination.read_text()
    assert evil not in html
    payload = html.split('<script id="report-data" type="application/json">')[1].split("</script>")[0]
    assert json.loads(payload)["metadata"]["filename"] == evil


def test_cli_offline_prevents_remote_even_with_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Netzwerkaufruf"))
    assert main([str(tmp_path / "missing.wav"), "--offline", "--remote"]) == 1
    assert main([str(tmp_path / "missing.wav"), "--offline", "--llm", "claude"]) == 1


def test_skip_transcribe_refuses_unrelated_source(tmp_path, monkeypatch):
    from pipeline import audio, transcribe

    source = tmp_path / "test.wav"
    source.touch()
    out = tmp_path / "output"
    out.mkdir()
    (out / "transcript.json").write_text(json.dumps({"transcription_key": "different"}))
    monkeypatch.setattr(audio, "prepare", lambda *args: (source, {"sha256": digest("new"), "duration": 3}))
    monkeypatch.setattr(transcribe, "local_transcribe", lambda *a, **k: pytest.fail("Neue Transkription"))
    assert main([str(source), "--out", str(out), "--skip-transcribe"]) == 1


def test_srt_rounds_carry_correctly():
    assert timestamp(59.9999, True) == "00:01:00,000"
