# Beitragen

Fehlerberichte und kleine, nachvollziehbare Pull Requests sind willkommen. Beschreibe bei Fehlern Betriebssystem, Python-Version, lokale Modelle, Schritte und die genaue Fehlermeldung. Verwende eine synthetische Aufnahme oder eine Beschreibung des Problems statt vertraulicher Interviews.

## Entwicklungsumgebung

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
ruff format --check .
```

ffmpeg/ffprobe werden für die Audio- und Exporttests benötigt. Die automatischen Tests verwenden Stubs für Cloud-Dienste und laden keine ML-Modelle herunter. Für vollständige lokale Analyseläufe zusätzlich `.[diarization]`, die Modellgewichte und Ollama einrichten.

Ändere bei einem Fehler möglichst nur den betroffenen Ablauf und ergänze einen Test, der das tatsächliche Problem abdeckt. Neue Cloud-Übermittlungen dürfen nicht zum stillen Standard werden. Beispielaufnahmen, Zugangsdaten, Modellgewichte und lokale Ausgaben bleiben ausserhalb von Git.

## Paket bauen

```bash
python -m pip install build
python -m build
```

`dist/` enthält das Quellarchiv und das Python-Wheel. Ein Release muss die Konfiguration, beide HTML-Templates, die bebilderte Tour sowie Lizenz- und Drittkomponentenhinweise enthalten. Die CI baut das Paket und prüft die installierten Einstiegspunkte ausserhalb des Checkouts.

Beiträge stehen wie der Projektcode unter der MIT-Lizenz. Die eigenen Bedingungen externer Abhängigkeiten und Modelle bleiben bestehen.
