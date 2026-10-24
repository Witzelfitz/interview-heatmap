"""Öffentlich verteilte noScribe-Modellgewichte, versioniert und per SHA-256 geprüft.

Es wird kein noScribe-Programmcode übernommen. Attribution der Gewichte:
pyannote / CNRS / pyannoteAI, WeSpeaker (Wang et al., ICASSP 2023),
BUT Speech@FIT (VBx/PLDA); Distribution: Kai Dröge / noScribe.
Siehe THIRD_PARTY_NOTICES.md für die ursprünglichen Quellen und Lizenzen.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from .common import file_hash

log = logging.getLogger(__name__)
REVISION = "e0c988a61efaa9b8da3a8016d667509bdacb1a68"
ASSETS = {
    "segmentation/pytorch_model.bin": (
        5906507,
        "7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e",
    ),
    "embedding/pytorch_model.bin": (
        26646242,
        "6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929",
    ),
    "plda/plda.npz": (133852, "9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255"),
    "plda/xvec_transform.npz": (134376, "325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f"),
}


def model_directory():
    root = Path(os.environ.get("INTERVIEW_HEATMAP_MODEL_DIR", Path.home() / ".cache" / "interview-heatmap"))
    return root.expanduser().resolve() / f"noscribe-community-1-{REVISION[:12]}"


def models_ready(directory=None):
    root = Path(directory) if directory else model_directory()
    return all(
        (root / name).is_file() and (root / name).stat().st_size == size for name, (size, _) in ASSETS.items()
    )


def download_asset(name, destination):
    size, expected_hash = ASSETS[name]
    url = f"https://raw.githubusercontent.com/kaixxx/noScribe/{REVISION}/pyannote/{name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".download-", delete=False) as output:
            temporary = Path(output.name)
            actual, total = hashlib.sha256(), 0
            with urlopen(url, timeout=90) as source:
                while block := source.read(1024 * 1024):
                    total += len(block)
                    if total > size:
                        raise ValueError("Modell-Download überschreitet die erwartete Dateigrösse")
                    actual.update(block)
                    output.write(block)
        if total != size or actual.hexdigest() != expected_hash:
            raise ValueError(
                "Prüfsumme des Sprecher-Modells stimmt nicht. Unvollständiger Download verworfen."
            )
        temporary.replace(destination)
    except (OSError, URLError) as exc:
        raise RuntimeError(
            "Sprecher-Modell konnte nicht heruntergeladen werden. Für die einmalige Einrichtung Internetverbindung prüfen; es werden keine Interviewdaten versendet."
        ) from exc
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def ensure_models(directory=None, offline=False):
    root = Path(directory) if directory else model_directory()
    for name, (size, expected_hash) in ASSETS.items():
        path = root / name
        valid = path.is_file() and path.stat().st_size == size and file_hash(path) == expected_hash
        if valid:
            continue
        if offline:
            raise ValueError(
                "Lokale Sprecher-Modelle fehlen oder sind beschädigt. Einmal ohne --offline starten, damit die öffentlichen noScribe-Modelle geladen werden."
            )
        log.info("Sprecher-Modell laden: %s (%.1f MB, kein Konto erforderlich)", name, size / 1e6)
        download_asset(name, path)
    # Eigene Konfiguration aus der öffentlichen community-1-Spezifikation.
    # Alle Referenzen sind Dateien im geprüften Cache, keine Hub-/Cloud-Pipelines.
    configuration = {
        "dependencies": {"pyannote.audio": "4.0.0"},
        "pipeline": {
            "name": "pyannote.audio.pipelines.SpeakerDiarization",
            "params": {
                "clustering": "VBxClustering",
                "segmentation": "$model/segmentation",
                "segmentation_batch_size": 32,
                "embedding": "$model/embedding",
                "embedding_batch_size": 32,
                "embedding_exclude_overlap": True,
                "plda": "$model/plda",
            },
        },
        "params": {
            "clustering": {"threshold": 0.6, "Fa": 0.07, "Fb": 0.8},
            "segmentation": {"min_duration_off": 0.0},
        },
    }
    config = root / "config.yaml"
    content = yaml.safe_dump(configuration, sort_keys=False)
    if not config.exists() or config.read_text() != content:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=root, prefix=".config-", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        temporary.replace(config)
    attribution = root / "ATTRIBUTION.txt"
    if not attribution.exists():
        attribution.write_text(
            "Local speaker models: pyannote community-1 / segmentation (Herve Bredin, CNRS, pyannoteAI), "
            "WeSpeaker (Wang et al., ICASSP 2023), VBx/PLDA (BUT Speech@FIT).\n"
            "Distribution: Kai Droege / noScribe and contributors.\n"
            f"Source revision: https://github.com/kaixxx/noScribe/tree/{REVISION}/pyannote\n"
            "Original model card / CC-BY-4.0: https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "Embedding attribution: https://github.com/kaixxx/noScribe/tree/main/pyannote/embedding\n"
            "Model weights retain their original terms, not this application's MIT license.\n",
            encoding="utf-8",
        )
    return root
