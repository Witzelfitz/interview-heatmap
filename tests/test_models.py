import hashlib
import io

import pytest
import yaml

from pipeline import models


@pytest.fixture
def tiny_assets(monkeypatch):
    values = {name: ("test weights for " + name).encode() for name in models.ASSETS}
    monkeypatch.setattr(
        models,
        "ASSETS",
        {name: (len(value), hashlib.sha256(value).hexdigest()) for name, value in values.items()},
    )
    return values


def test_first_download_needs_no_token_and_uses_pinned_sources(tmp_path, tiny_assets, monkeypatch):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        assert models.REVISION in url and "raw.githubusercontent.com/kaixxx/noScribe/" in url
        assert "token" not in url and "Authorization" not in kwargs
        return io.BytesIO(tiny_assets[url.split("/pyannote/", 1)[1]])

    monkeypatch.setattr(models, "urlopen", fetch)
    result = models.ensure_models(tmp_path)
    assert len(calls) == 4 and models.models_ready(result)
    config = yaml.safe_load((result / "config.yaml").read_text())
    assert config["pipeline"]["name"] == "pyannote.audio.pipelines.SpeakerDiarization"
    assert config["pipeline"]["params"]["embedding"] == "$model/embedding"
    models.ensure_models(tmp_path, offline=True)
    assert len(calls) == 4  # Wiederholter Offline-Lauf kontaktiert keinen Downloadserver.


def test_corrupt_download_is_not_installed_and_temporary_file_removed(tmp_path, tiny_assets, monkeypatch):
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="Prüfsumme"):
        models.ensure_models(tmp_path)
    assert not list(tmp_path.rglob("pytorch_model.bin"))
    assert not list(tmp_path.rglob(".download-*"))


def test_offline_does_not_attempt_model_download(tmp_path, tiny_assets, monkeypatch):
    monkeypatch.setattr(models, "urlopen", lambda *_a, **_k: pytest.fail("Kein Netzwerk im Offline-Modus"))
    with pytest.raises(ValueError, match="ohne --offline"):
        models.ensure_models(tmp_path, offline=True)


def test_corrupt_cached_weights_require_repair(tmp_path, tiny_assets, monkeypatch):
    monkeypatch.setattr(
        models, "urlopen", lambda url, **_kwargs: io.BytesIO(tiny_assets[url.split("/pyannote/", 1)[1]])
    )
    models.ensure_models(tmp_path)
    name = next(iter(tiny_assets))
    (tmp_path / name).write_bytes(b"x" * len(tiny_assets[name]))
    with pytest.raises(ValueError):
        models.ensure_models(tmp_path, offline=True)
    models.ensure_models(tmp_path)
    assert (tmp_path / name).read_bytes() == tiny_assets[name]
