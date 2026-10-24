import copy
from pathlib import Path

import pytest

from heatmap import load_config


@pytest.fixture
def config():
    return load_config(Path(__file__).parents[1] / "config.yaml")


@pytest.fixture
def segments():
    """Künstliche Zeitwerte ausschliesslich für Unit-Tests, keine Demo als echte Analyse."""
    rows = []
    for i in range(48):
        tokens = (
            "Warum hat mich diese persönliche Geschichte plötzlich so berührt?"
            if i % 3 == 0
            else "Ich dachte an meine Familie und musste plötzlich weinen."
        ).split()
        start = i * 8 + 0.1
        words = [
            {"word": text, "start": start + j * 0.6, "end": start + j * 0.6 + 0.4, "speaker": f"S{i % 2 + 1}"}
            for j, text in enumerate(tokens)
        ]
        rows.append(
            {
                "id": i,
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "speaker": f"S{i % 2 + 1}",
                "text": " ".join(tokens),
                "words": words,
            }
        )
    return copy.deepcopy(rows)


@pytest.fixture
def analyzed(segments, config):
    from pipeline.analyze import local_analysis
    from pipeline.cuts import proposals
    from pipeline.scoring import score

    analysis = local_analysis(segments)
    features = [{"segment_id": s["id"], "audio_score": 0.4 + (s["id"] % 7) / 15} for s in segments]
    scored = score(segments, features, analysis, 384, config["scoring"])
    cuts = proposals(scored, analysis, 384, config["cuts"])
    return {
        "metadata": {
            "filename": "Testinterview.wav",
            "sha256": "test",
            "duration": 384,
            "media_type": "audio",
            "media_file": "Testinterview.wav",
            "diarization": "imported_turns",
        },
        "analysis": analysis,
        "scored": scored,
        "cuts": cuts,
        "transcript": {"segments": segments},
        "exports": {"cuts.edl": "TITLE: TEST\nFCM: NON-DROP FRAME\n", "transcript.srt": "1\n"},
    }
