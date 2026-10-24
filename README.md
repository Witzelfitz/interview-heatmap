# Interview Heatmap & Schnitt-Advisor

Eine lokale Python-Pipeline für Interview-Aufnahmen: Wort-Zeitstempel, Sprecher, Audio-Merkmale, Heat-Kurve und Schnittvorschläge. Ergebnis: **ein eigenständiger HTML-Report ohne Build, Server oder CDN**, dazu JSON, SRT, TXT und CMX3600-EDLs.

![Report mit Heat-Kurve und Schnittspuren](docs/preview.png)

## Installation

Empfohlen: **Python 3.12**; Mindestversion 3.11. ffmpeg und ffprobe müssen im PATH liegen.

```bash
# macOS
brew install python@3.12 ffmpeg
# Ubuntu/Debian: sudo apt-get install python3-venv ffmpeg libsndfile1

git clone https://github.com/Witzelfitz/interview-heatmap.git
cd interview-heatmap
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[diarization]'
```

Für die lokale Sprechererkennung:

1. Die Modellbedingungen von [pyannote community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) selbst akzeptieren.
2. Einen Hugging-Face-Token mit Leserechten für das Modell erstellen.
3. `HF_TOKEN` in der lokalen Shell setzen. Keine Schlüssel ins Repository schreiben.

Das erste Ausführen lädt Whisper- und pyannote-Modellgewichte herunter. Dabei wird **kein Audio hochgeladen**. Danach sind lokale Modellpfade und `--offline` möglich. Die Modellbedingungen und Attribution von pyannote gelten zusätzlich zum Projektcode.

## Ein Befehl

```bash
python heatmap.py interview.mp4 --out ./output --lang de
```

`output/report.html` per Doppelklick öffnen. Die extrahierte `audio.wav` liegt bereits daneben. Bei fehlendem Originalvideo verwendet der Player diese Audiospur. Mit `--copy-media` wird auch das Original zum Report kopiert; alternativ im Report **Medium wählen**. Die Datei wird dabei ausschliesslich im Browser geöffnet.

Standardmässig laufen **Transkription, Diarisierung und Audio-Analyse lokal**. Ohne LLM-Flag liefert eine deutlich gekennzeichnete Schlüsselwort-Heuristik erste Scores und Strukturvorschläge. Eine inhaltliche Drei-Satz-Zusammenfassung, semantische Kapitel und redaktionell begründete Dramaturgie benötigen den folgenden optionalen Modus.

## Inhaltliche Analyse mit Claude

```bash
python -m pip install -e '.[claude]'
# ANTHROPIC_API_KEY in der lokalen Shell setzen
python heatmap.py interview.mp4 --out ./output --lang de --skip-transcribe --llm claude
```

**`--llm claude` übermittelt Transkripttext an Anthropic.** Audio bleibt lokal. Ein vorhandener API-Key allein aktiviert keine Übermittlung. Der erste Durchgang bewertet überlappende 150-Sekunden-Fenster, der zweite das gesamte Transkript mit Abschnittszusammenfassungen und Scores. Claude empfiehlt auch Hooks und eigenständige Clips; die Pipeline prüft deren IDs, Dauer und reale Satzgrenzen. Ungültige Schnittfenster werden durch lokal gerankte Kandidaten ersetzt.

Modell und Fenstergrössen stehen in `config.yaml`. Vollständige strukturierte Antworten werden per JSON-Schema validiert. Nicht belegbare Zitate werden verworfen, ebenso unzulässige Scores; erfundene Segment-IDs oder überlappende Kapitel brechen den Lauf ab. Es gibt keinen stillen Wechsel von einem fehlgeschlagenen Claude-Aufruf zur Heuristik.

## Transkriptionsoptionen

```bash
# Nur Schritt 1–2, z.B. zum Prüfen einer kurzen Aufnahme
python heatmap.py test.mp4 --out output --transcribe-only

# Aufnahme mit tatsächlich nur einer Stimme (keine Sprechererkennung behaupten)
python heatmap.py monolog.wav --out output --single-speaker

# Zwei bekannte Stimmen; pyannote berechnet die Zuordnung weiterhin selbst
python heatmap.py interview.mp4 --out output --speakers 2

# CPU / geringerer Ressourcenbedarf
python heatmap.py interview.mp4 --out output --model medium --device cpu --compute-type int8

# Vorhandene, echte Diarisierung importieren
python heatmap.py interview.mp4 --out output --diarization-file turns.json
```

Format von `turns.json`: eine Liste mit `start`, `end` in Sekunden und `speaker` als ursprünglichem Label. Labels werden nach ihrem ersten Auftreten zu `S1`, `S2` usw. normalisiert. Nicht zuordenbare Wörter heissen **Unbekannt**. Überlappende Sprecherbereiche sind erlaubt. Ohne pyannote-Zugang wird keine erfundene Mehrsprecher-Erkennung angeboten; das bereits berechnete Whisper-Ergebnis bleibt im Cache.

Automatische Modellwahl: `large-v3` bei CUDA und ausreichend verfügbarem RAM, sonst `medium`. Bei Speicherfehlern von `large` folgt ein Versuch mit `medium` auf CPU/int8. Ein explizites `--model large-v3` ist möglich. faster-whisper nutzt auf Apple Silicon hier CPU/int8, keine Metal-GPU. Für NVIDIA müssen die zur installierten CTranslate2-Version passenden CUDA/cuDNN-Bibliotheken vorhanden sein, siehe [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

Schweizerdeutsch wird näherungsweise ins Hochdeutsche transkribiert. CH-Orthografie wird vor der Zitatprüfung vereinheitlicht (`ß` → `ss`); jedes angezeigte Zitat muss danach ein **exakter zusammenhängender Teilstring seines Segments** sein. ASR-Zeitstempel und Sprecherlabels bleiben Modellschätzungen und müssen vor einem finalen Schnitt kontrolliert werden.

## Optional: Whisper-API

```bash
python -m pip install -e '.[remote]'
# OPENAI_API_KEY in der lokalen Shell setzen
python heatmap.py interview.mp4 --out remote-output --remote
```

**Nur `--remote` sendet Audio an OpenAI**, mit einem Warnhinweis in der Konsole. Die API liefert Wort-Zeitstempel über `whisper-1`/`verbose_json`. Längere WAV-Dateien werden in 600-Sekunden-Blöcke unter 25 MB aufgeteilt; Zeitstempel werden um den jeweiligen echten Blockoffset verschoben. An Blockgrenzen kann Kontext fehlen. Die Diarisierung bleibt lokal. Siehe die [offizielle Speech-to-Text-Dokumentation](https://developers.openai.com/api/docs/guides/speech-to-text).

## Cache und strikter Offline-Modus

```bash
# Dieselbe Quelle und dieselben Transkriptions-/Sprecheroptionen verwenden:
python heatmap.py interview.mp4 --out output --skip-transcribe

# Nur bereits heruntergeladene bzw. lokale Modelle verwenden:
python heatmap.py interview.mp4 --out output --offline \
  --model /pfad/zu/whisper-medium-ct2 \
  --diarization-model /pfad/zu/pyannote-community-1
```

`--offline` lehnt `--remote` und `--llm claude` ab und aktiviert den Offline-Modus von Hugging Face. pyannote-Telemetrie und Hugging-Face-Telemetrie sind immer deaktiviert. Ein Offline-Lauf benötigt sämtliche Modellgewichte bereits lokal; ein Token ersetzt diese Gewichte nicht.

SHA-256 der Quelle, Sprache, Modell, Device, Präzision und Sprecheroptionen bestimmen den Transkript-Cache. Bei einem abweichenden Fingerprint bricht `--skip-transcribe` ab. Audio-Merkmale, einzelne LLM-Fenster und der Gesamtpass werden separat gecacht. Änderungen an Heat-Gewichten benötigen keine neue Transkription. Cache-Dateien werden atomar geschrieben. Zum gezielten Wiederholen einer Analyse die passende Datei in `output/cache/` entfernen.

## Scores und Schnittlogik

- RMS, Pitch-Variation in Halbtönen, Wörter/Sekunde, Pause vor dem Segment und Sprecherüberlappung werden pro Stimme mit z-Scores normalisiert. Nahezu konstante Pitch-Varianz wird nicht durch Messrauschen verstärkt. Audio-Score: Sigmoid aus gewichteten z-Scores.
- Lachen wird mangels zuverlässigem Klassifikator als `null` exportiert, nicht als vermeintlich gemessener Wert. Pitch aus YIN bleibt ein akustischer Erregungsindikator, keine Emotionsmessung.
- `heat_final = 0.6 * (heat_llm / 10) + 0.4 * audio_score`; ohne Claude ersetzt die gekennzeichnete Heuristik `heat_llm`. Gewichte in `config.yaml` müssen zusammen 1 ergeben.
- Ein-Sekunden-Kurve mit gleitendem Mittel über 15 Sekunden; Peaks über Mindestabstand und Prominenz. Stille wird als 0 berücksichtigt.
- Hooks: vollständige Sätze in 5–15 Sekunden. Social Clips: 15–60 Sekunden, höchstens acht nicht überlappende Vorschläge, Schluss und verifizierte Zitate werden bevorzugt. Fehlt geeignetes Material, werden weniger Vorschläge mit Hinweis ausgegeben.
- Kurzfassungen: chronologisch, Einstieg und Abschluss sowie starke Passagen je Dramaturgiephase. Gesamtdauer inklusive zusammengefügter Pausen bleibt im Zielbudget. Bei kurzem Ausgangsmaterial oder fehlenden Satzgrenzen ist die Auswahl kürzer.
- Kürzungshinweise: niedriger Heat, exakte Wiederholungen, dichte Füllwörter. Retention-Risiken: durchgehend mehr als 90 Sekunden unter dem konfigurierbaren Schwellenwert. Das sind redaktionelle Hypothesen, keine gemessenen Zuschauerreaktionen.

Schnitte verwenden echte Wortzeiten und erkannte Satzenden. Pausen-Puffer werden auf die tatsächlich freie Zeit bis zum Nachbarwort begrenzt. Bei der EDL-Frame-Rundung werden angeschnittene Nachbarwörter vollständig eingeschlossen. Das kann zusätzliche Wörter hinzufügen; JSON-Sekunden und EDL-Frames können daher leicht abweichen. Inhaltlicher Zusammenhang und eine Pointe lassen sich auch mit LLM nicht garantieren.

## Ausgaben

| Datei | Inhalt |
|---|---|
| `report.html` | Single-File-Report mit sämtlichen Analysedaten, Inline-CSS/JS, Export-Buttons |
| `report.json` | Gesamtdaten einschliesslich Exporttexten und Herkunft |
| `transcript.json` / `.srt` / `.txt` | Wortzeiten, Sprecher und Transkript |
| `audio_features.json` | Rohwerte, z-Scores und Audio-Score |
| `analysis.json` | Inhalt, belegte Zitate, Kapitel, Phasen, Höhepunkte |
| `heatmap.json` | Kombinierte Segment-Scores, Kurve und Peaks |
| `cuts.json` | Hook, Clips, Kurzfassungen, Kürzungen, Retention-Hinweise |
| `cuts.edl` | Standardmässig 5-Minuten-Auswahl, sonst Social-Clip-Auswahl |
| `hook.edl`, `clips.edl`, `short-3.edl` usw. | Separate Schnittsequenzen |
| `render-clips.sh`, `clips/*.srt` | Exakte ffmpeg-Kommandos und cliprelative Untertitel |
| `audio.wav`, `cache/` | Lokale Arbeitsdateien und wiederverwendbare Zwischenergebnisse |

Im Report: Zeitachse und Transkript sind gegenseitig verknüpft. Ein Clip spielt bis zu seinem Ende; Untertitel lassen sich pro Clip laden. Sprecher können lokal umbenannt werden; Namen und Farbschema bleiben im Browser gespeichert, und der JSON-Download enthält `speaker_names`. Der EDL-Button exportiert die gewählte Schnittversion. Das JSON enthält volle Daten, die Mediendatei bleibt separat. Bei Weitergabe nur des HTML-Reports funktioniert die gesamte Analyse; für Wiedergabe das Medium zusätzlich danebenlegen oder lokal auswählen.

## Clips rendern

```bash
python heatmap.py interview.mp4 --out output --skip-transcribe --render-clips
# Oder das erzeugte Skript später ausführen:
sh output/render-clips.sh
```

Hook und Social Clips werden mit Video/AAC bzw. Audio/AAC neu codiert. Kein ungenauer Stream-Copy-Schnitt an einem entfernten Keyframe. Es gibt keine automatische Hochformat-Beschneidung; Bildausschnitt und Gesichter vor der Veröffentlichung prüfen. Kurzfassungen sind zunächst Schnittlisten/EDLs, keine gerenderten Zusammenstellungen.

## EDL in Premiere / DaVinci Resolve

CMX3600, 24/25/30 fps **non-drop-frame**, Source-Start standardmässig `00:00:00:00`, Record-Start `01:00:00:00`. Video-EDLs verwenden `AA/V`, Audio-EDLs `A`. `* FROM CLIP NAME` enthält den Originaldateinamen, Reel ist `AX`. Medien müssen im Schnittprogramm lokal verknüpft werden.

1. Projekt-/Sequenz-Framerate passend zur Aufnahme wählen. `cuts.edl_fps` in einer Config setzen; 29.97/59.94 drop-frame wird nicht unterstützt. Bei VFR-Material vorab eine konstante Framerate herstellen und diese Datei analysieren.
2. Bei Quellmaterial mit eigenem Start-Timecode `--source-timecode 01:00:00:00` verwenden. Der CLI-Standard übernimmt den Container-Timecode nicht automatisch.
3. In Resolve **File → Import → Timeline**, in Premiere die EDL über **Datei → Importieren** öffnen. Originalmedium relinken, ggf. im Dialog die Framerate angeben.
4. Source-In/Out, Record-Dauer, Audio-/Videospuren und mehrere Übergänge gegen Transkript und Player prüfen. EDL ist verlustbehaftet und enthält keine Untertitel oder Effekte.

Die erzeugten Audio- und `AA/V`-Video-EDLs wurden mit dem unabhängigen OpenTimelineIO-CMX3600-Parser gelesen. Ein Import in Premiere/Resolve ist **noch nicht bestätigt**: Der Computerzugriff auf das installierte Premiere wurde vom Werkzeug nicht freigegeben.

## Tests und bisherige Validierung

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check .
ruff format --check .

# macOS: 2:50 Minuten synthetisches Zweistimmen-Interview erzeugen
python scripts/make_test_audio.py
python heatmap.py .local-tests/interview.wav --out test-output --model tiny \
  --diarization-file .local-tests/turns.json
python -m playwright install chromium
python scripts/verify_report.py test-output/report.html
```

Die Testaufnahme ist eine selbst erzeugte fiktive Geschichte. Importierte Sprecherbereiche stammen aus den echten Grenzen der synthetisierten Sprachdateien. Wortzeiten und Text werden tatsächlich mit Whisper berechnet, nicht als Demo erfunden.

Auf dem Entwicklungsrechner geprüft:

- 2:50-Minuten-Aufnahme mit `tiny`/CPU/int8: reale lokale Transkription, Wortzeiten, zwei importierte Stimmen, Audio-Merkmale, Report, SRT/JSON/EDL und Clip-Rendering.
- Dieselbe Aufnahme zusätzlich mit `medium`/CPU/int8: erfolgreiche vollständige Pipeline mit dem CPU-Standardmodell. Ein weiterer echter `tiny`-Lauf bestand mit auf Python-Ebene blockierten TCP-Verbindungen.
- 60 Minuten wiederholte synthetische Sprache, `tiny`/CPU/int8, `--offline`: vollständige Pipeline, 7'655 Wörter, 755 Segmente, 64 Peaks, acht Social Clips. Dauer ca. 112 Sekunden, maximaler Resident-Speicher ca. 5.1 GB. Dies ist kein Benchmark für natürliche Interviews oder `medium`/`large-v3`.
- Browser unter `file://`: korrekter Clip-Start und -Stopp, Suche, gespeicherte Sprechernamen, Downloads, Dark Mode und 768px Breite; keine HTTP-Aufrufe.
- Automatische Tests für echte Zitatprüfung, Cache-Invalidierung, individuelle Sprecher-Normalisierung, Zeitbudgets, Schnittgrenzen, EDL-Timecodes, HTML-Injection, LLM-Verträge und Remote-Chunk-Offsets.

**Noch extern zu prüfen:** automatische pyannote-Diarisierung mit freigeschaltetem Modell, echte Claude-/OpenAI-API-Aufrufe, NLE-Import und natürliche lange Schweizerdeutsch-Interviews. Hier wurden keine API-Schlüssel bereitgestellt. API-Tests verwenden Stubs und lösen keine kostenpflichtigen Aufrufe aus.

## Datenschutz

Lokale Verarbeitung unterstützt einen datensparsamen Workflow, ist aber keine pauschale CH-DSG-Konformitätszusage. Transkript, Sprecherzuordnung und Audiodateien können personenbezogene Informationen enthalten. Ausgabeordner, Cache und Reports entsprechend schützen. Vor einem Remote-Modus die konkrete Übermittlung und deren Rechtsgrundlage/Verträge prüfen. Das Projekt lädt keine Interviewdaten automatisch hoch; auch Git ignoriert Ausgaben, Testmedien und `.env`-Dateien.

## Struktur

```text
heatmap.py
pipeline/{audio,transcribe,analyze,scoring,cuts,report,common}.py
templates/report.html
config.yaml
scripts/{make_test_audio,verify_report}.py
tests/
```

Referenzen: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [community-1](https://huggingface.co/pyannote/speaker-diarization-community-1), [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [OpenAI Speech to Text](https://developers.openai.com/api/docs/guides/speech-to-text).
