# Drittkomponenten und Modellgewichte

Die MIT-Lizenz in diesem Repository gilt für den eigenen Projektcode. Die folgenden
Projekte und Modelle bleiben unter ihren jeweiligen Bedingungen. Die Links sind
die massgeblichen Quellen. Das Repository enthält keine Modellgewichte; die Anwendung lädt die unten bezeichneten Sprechergewichte beim ersten Gebrauch in einen lokalen Cache.

| Komponente | Herkunft / Bedingungen |
|---|---|
| Ollama | [Quellcode und MIT-Lizenz](https://github.com/ollama/ollama) |
| Whisper | [Quellcode, Gewichte und MIT-Lizenz](https://github.com/openai/whisper) |
| faster-whisper | [Quellcode und MIT-Lizenz](https://github.com/SYSTRAN/faster-whisper) |
| pyannote.audio | [Quellcode und MIT-Lizenz](https://github.com/pyannote/pyannote-audio) |
| Lokale Sprechergewichte / community-1 | [Ursprüngliche Modellkarte und CC-BY-4.0](https://huggingface.co/pyannote/speaker-diarization-community-1); bezogen aus der [öffentlichen noScribe-Distribution](https://github.com/kaixxx/noScribe/tree/e0c988a61efaa9b8da3a8016d667509bdacb1a68/pyannote), ohne Hub-Anmeldung |
| WeSpeaker-Embedding | Wang et al., *WeSpeaker: A research and production oriented speaker embedding learning toolkit*, ICASSP 2023. [Herkunft und Attribution](https://github.com/kaixxx/noScribe/blob/e0c988a61efaa9b8da3a8016d667509bdacb1a68/pyannote/embedding/README.md); VoxCeleb-bezogene CC-BY-4.0-Bedingungen |
| PLDA / VBx-Gewichte | BUT Speech@FIT; [Quellhinweise der Distribution](https://github.com/kaixxx/noScribe/blob/e0c988a61efaa9b8da3a8016d667509bdacb1a68/pyannote/plda/README.md) |
| gpt-oss | [Offene Gewichte unter Apache 2.0](https://openai.com/open-models/); die weiteren Modellbedingungen und die Usage Policy des Anbieters beachten |
| ffmpeg | [Lizenzinformationen](https://ffmpeg.org/legal.html); konkrete LGPL-/GPL-Bedingungen hängen vom installierten Build ab |

Bei Wahl eines anderen Ollama-Modells dessen Lizenz prüfen. Ein lokal ausführbares
Modell ist nicht automatisch unter einer Open-Source-Lizenz veröffentlicht. Das
Projekt benutzt die Begriffe Open-Source-Code und offene Modellgewichte getrennt.

Claude und OpenAI-Whisper-API sind optionale externe Dienste mit eigenen Verträgen.
Sie werden für den standardmässigen lokalen Ollama-Workflow nicht benötigt.

Die Modellintegration verwendet selbst geschriebenen Download-/Konfigurationscode
und die API von pyannote.audio. noScribe ist ein separates GPL-3.0-Projekt; dessen
Programmcode und die Desktop-Anwendung werden hier nicht übernommen oder gebündelt.
Die Bezugsquelle wird mit vollständiger Git-Revision und SHA-256 je Datei fixiert
(siehe `pipeline/models.py`). noScribe: Kai Dröge und Beitragende; pyannote: Hervé
Bredin, CNRS, pyannoteAI und Beitragende. Die Modellgewichte bleiben unter ihren
ursprünglichen Bedingungen; die MIT-Lizenz dieses Projekts lizenziert sie nicht um.
