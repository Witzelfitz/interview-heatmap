# Schnittplatz – Interview Heatmap & Schnitt-Advisor

Interviews lokal transkribieren, interessante Stellen finden und einen ersten Schnitt vorbereiten. Entstanden im CAS Hands-on LLM an der FH Graubünden, Oktober 2026.

Die Anwendung verbindet Whisper, lokale Sprechererkennung und Ollama. Du lädst eine Aufnahme im Browser auf deinen eigenen Rechner, erhältst eine Heatmap mit Transkript und prüfst Vorschläge für Hook, Social Clips und Kurzfassungen. Der fertige HTML-Report funktioniert auch ohne laufenden Server.

![Report mit Heatmap, Sprecherzuordnung und Schnittvorschlägen](docs/preview.png)

**[Bebilderte Vorstellung als PDF](docs/vorstellung.pdf)** · **[Technischer Leitfaden](docs/technical-guide.md)** · **[Releases und Downloads](https://github.com/Witzelfitz/interview-heatmap/releases)**

## Was du erhältst

- Wort-Zeitstempel und Sprecherzuordnung, auch für deutschsprachige Interviews.
- Inhaltliche Analyse mit einem lokalen Ollama-Modell und akustische Merkmale pro Stimme.
- Interaktive Heatmap, durchsuchbares Transkript und direkt abspielbare Schnittvorschläge.
- Exporte als HTML, JSON, SRT, TXT und EDL für die weitere Bearbeitung.
- Auf Wunsch gerenderte Hook- und Social Clips mit ffmpeg.

Die Vorschläge unterstützen redaktionelle Entscheidungen. Sie messen keine tatsächliche Zuschauerbindung. Schweizerdeutsch wird näherungsweise ins Hochdeutsche übertragen; Aussagen, Sprecher und Schnittgrenzen müssen geprüft werden.

## Voraussetzungen

| Voraussetzung | Hinweis |
|---|---|
| Python | Ab 3.11, empfohlen 3.12. CI prüft 3.11–3.13 auf Linux. |
| ffmpeg und ffprobe | Beide müssen im `PATH` liegen. |
| Ollama mit lokalem Chat-Modell | Für die voreingestellte Inhaltsanalyse. Ein kleineres vorhandenes Modell ist in der Oberfläche wählbar. |
| Speicher und Internet beim ersten Start | Whisper und Sprechererkennung laden ihre Modellgewichte einmal herunter. Interviewdaten bleiben dabei lokal. |

Auf macOS kannst du Python und ffmpeg mit `brew install python@3.12 ffmpeg` installieren. Auf Ubuntu/Debian: `sudo apt-get install python3 python3-venv ffmpeg libsndfile1`. Verwende unten den passenden Python-Interpreter, zum Beispiel `python3.12` nach der Homebrew-Installation.

## Schnellstart auf macOS und Linux

```bash
git clone https://github.com/Witzelfitz/interview-heatmap.git
cd interview-heatmap
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[diarization]'
```

[Ollama installieren](https://ollama.com/download), starten und ein lokales Chat-Modell bereitstellen. Das voreingestellte Modell wurde auf einem Rechner mit 36 GiB RAM verwendet und kann für kleinere Geräte zu gross sein:

```bash
ollama pull gpt-oss:20b
python server.py --port 8767
```

Öffne **[http://localhost:8767](http://localhost:8767)**, wähle deine Aufnahme und klicke auf **Interview hochladen & analysieren**. Wenn du ein anderes Modell installiert hast, wähle es in den Einstellungen. Die automatische Sprechererkennung benötigt kein Konto und keinen Hugging-Face-Token.

Der Server muss während der Analyse laufen. Neue Uploads und Ergebnisse liegen unter `output/uploads/`. Der erste Lauf dauert durch Modelldownloads länger. Mit `Ctrl+C` beendest du den Server.

### Windows

Python 3.12, ffmpeg/ffprobe und Ollama müssen installiert sein. In PowerShell kannst du ohne Aktivierungsskript arbeiten:

```powershell
git clone https://github.com/Witzelfitz/interview-heatmap.git
cd interview-heatmap
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[diarization]"
ollama pull gpt-oss:20b
.\.venv\Scripts\python.exe server.py --port 8767
```

Die Windows-Anleitung ist bislang nicht durch einen vollständigen Analyselauf auf Windows bestätigt. Die bisherigen vollständigen lokalen Läufe erfolgten auf macOS; automatische Tests laufen auf Linux.

## Nutzung über die Kommandozeile

```bash
python heatmap.py interview.mp4 --out output --lang de
# Ein vorhandenes kleineres Ollama-Modell wählen:
python heatmap.py interview.mp4 --out output --ollama-model MEIN_LOKALES_MODELL
# Ohne LLM: ausdrücklich gekennzeichnete Heuristik:
python heatmap.py interview.mp4 --out output --llm local
```

Danach `output/report.html` öffnen. Für die Wiedergabe die Aufnahme mitgeben oder im Report lokal auswählen. Automatische Sprechererkennung benötigt das oben installierte Extra `diarization`.

Weitere Optionen zu Offline-Betrieb, Modellen, Caches, EDL und Cloud-Diensten stehen im [technischen Leitfaden](docs/technical-guide.md).

## Daten und lokale Verarbeitung

Im Standardmodus laufen Transkription, Sprechererkennung und Inhaltsanalyse lokal. Der Server lauscht nur auf `127.0.0.1`; Ollama wird ebenfalls nur über Loopback angesprochen. Ohne laufendes Ollama erscheint eine Fehlermeldung; die Anwendung wechselt nicht still zu einem anderen Analysemodus.

Die optionalen Cloud-Modi werden ausdrücklich gewählt: `--llm claude` sendet Transkripttext an Anthropic, `--remote` sendet Audio an OpenAI. Für den lokalen Ablauf brauchst du keine API-Schlüssel. Modellgewichte haben eigene Lizenzen; siehe [Drittkomponenten](THIRD_PARTY_NOTICES.md).

Aufnahmen, erzeugte Reports, Modelle, Caches und lokale Zugangsdaten gehören nicht ins Repository. Die beiliegenden Screenshots und die Tour verwenden eine synthetische Demo-Aufnahme.

## Häufige Startprobleme

| Problem | Nächster Schritt |
|---|---|
| ffmpeg fehlt | `ffmpeg -version` und `ffprobe -version` in derselben Shell prüfen. |
| Ollama oder Modell fehlt | Ollama starten, mit `ollama list` die installierten Modelle prüfen und eines in der Oberfläche auswählen. |
| Sprechererkennung fehlt | In der aktiven Umgebung `python -m pip install -e '.[diarization]'` ausführen. |
| Modell passt nicht in den Speicher | Kleineres Ollama-Modell wählen und Whisper in den Einstellungen auf `small` oder `tiny` setzen. |
| Port 8767 ist belegt | `python server.py --port 8768` starten und `http://localhost:8768` öffnen. |

## Entwicklungsstand und Mitarbeit

Der Stand ist ein funktionsfähiger Workshop-Prototyp. Lokal getestet wurden synthetische Interviews, Sprechererkennung, Ollama-Analyse, Browser-Upload und Exporte. Noch nicht bestätigt sind echte Cloud-API-Läufe, der direkte EDL-Import in Premiere/Resolve und die Qualität an natürlichen langen Schweizerdeutsch-Interviews. Details und frühere Prüfläufe stehen im [technischen Leitfaden](docs/technical-guide.md#tests-und-bisherige-validierung).

Für Entwicklung und Tests siehe [CONTRIBUTING.md](CONTRIBUTING.md). Fehler und Verbesserungsvorschläge können über [GitHub Issues](https://github.com/Witzelfitz/interview-heatmap/issues) gemeldet werden.

## Lizenz

Eigener Projektcode: [MIT](LICENSE), Benjamin Hanimann. Abhängigkeiten und Modellgewichte behalten ihre jeweiligen [Lizenz- und Attributionsbedingungen](THIRD_PARTY_NOTICES.md).
