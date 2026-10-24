"""Bebilderte HTML-Tour und PDF aus authentischen Demo-Screenshots erstellen."""

from __future__ import annotations

import base64
import html
import json
import shutil
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"

PAGES = [
    {
        "id": "ueberblick",
        "label": "Überblick",
        "title": "Ein Interview. Ein Schnittplan.",
        "intro": "Schnittplatz hilft, Interviews zu verstehen und starke Passagen für den Schnitt zu finden.",
        "image": "05-heatmap.png",
        "caption": "Echte Heatmap einer synthetischen Demo-Aufnahme. Keine privaten Interviewinhalte.",
        "steps": [
            ("Verstehen", "Transkript, Sprecher und Kapitel machen das Gespräch durchsuchbar."),
            ("Prüfen", "Heat Moments und Dramaturgie führen zu Stellen, die sich anzuhören lohnen."),
            ("Planen", "Hook, Social Clips und Kurzfassungen liefern einen redaktionellen Ausgangspunkt."),
        ],
        "result": "Ein eigenständiger HTML-Report plus JSON, Untertitel und Schnittlisten.",
        "note": "Für Redaktion, Podcast und Video. Die Entscheidung über Aussage, Kontext und finalen Schnitt bleibt bei dir.",
    },
    {
        "id": "upload",
        "label": "Aufnahme",
        "title": "1. Aufnahme auswählen",
        "intro": "Eine Audio- oder Videodatei reicht. Die Standard-Einstellungen verarbeiten sie lokal.",
        "image": "01-upload-panel.png",
        "caption": "Datei gewählt, automatische Sprechererkennung aktiv. Die Analyse startet über den grünen Button.",
        "steps": [
            ("Datei wählen", "Audio oder Video in die Fläche ziehen oder über die Dateiauswahl öffnen."),
            (
                "Sprache und Sprecher",
                "Deutsch / Schweizerdeutsch und Automatisch erkennen wählen. Genau eine Stimme nur für entsprechende Aufnahmen nutzen.",
            ),
            (
                "Analyse starten",
                "Bei Bedarf die Einstellungen öffnen: Ollama und ein lokales Chat-Modell wählen. Dann Interview hochladen & analysieren drücken.",
            ),
        ],
        "result": "Die Datei wird an deinen lokalen Server übertragen und als eigener Auftrag verarbeitet.",
        "note": "Kein Konto und kein Token für die Sprechererkennung. Die rund 33 MB Sprechergewichte werden beim ersten Mal automatisch geladen.",
    },
    {
        "id": "analyse",
        "label": "Verarbeitung",
        "title": "2. Analyse verfolgen",
        "intro": "Die Verarbeitung läuft als Hintergrundauftrag. Die Oberfläche zeigt den aktuellen Schritt.",
        "image": "03-verarbeitung.png",
        "caption": "Tatsächlich laufender Demo-Auftrag. Die Anzeige zeigt einen Verarbeitungsschritt, keine garantierte Restlaufzeit.",
        "steps": [
            (
                "Audio und Text",
                "Audiospur vorbereiten, Wörter transkribieren und Sprecher automatisch zuordnen.",
            ),
            (
                "Bewerten und planen",
                "Audio-Merkmale, lokale Inhaltsanalyse, Heat-Kurve und Schnittvorschläge berechnen.",
            ),
            (
                "Ergebnis öffnen",
                "Bei offenem Tab erscheint der Report automatisch. Später lässt er sich unter Deine Interviews öffnen.",
            ),
        ],
        "result": "Report, Rohdaten und Exporte liegen zusammen im lokalen Auftragsordner.",
        "note": "Server und Ollama weiterlaufen lassen. Der Browser-Tab darf nach dem Upload geschlossen werden; mehrere Interviews warten nacheinander in der Queue.",
    },
    {
        "id": "heatmap",
        "label": "Heatmap",
        "title": "3. Das Gespräch lesen",
        "intro": "Die gemeinsame Zeitachse verbindet Intensität, Sprecher, Themen und Spannungsbogen.",
        "image": "05-heatmap.png",
        "caption": "Oben die geglättete Heat-Kurve, darunter Sprecher, Kapitel, Dramaturgie und die gewählte Schnitt-Ebene.",
        "steps": [
            (
                "Peaks ansehen",
                "Marker zeigen Heat Moments. Die Kurve kombiniert Audiosignale mit der inhaltlichen Bewertung.",
            ),
            (
                "Kontext finden",
                "Sprecher-Spuren, Kapitel und Dramaturgie helfen, die Stelle im Verlauf des Gesprächs einzuordnen.",
            ),
            (
                "Zur Passage springen",
                "Auf die Zeitachse oder einen markierten Höhepunkt klicken und die passende Transkriptstelle prüfen.",
            ),
        ],
        "result": "Du erhältst eine begründete Auswahl von Prüfstellen im gesamten Interview.",
        "note": "Ein hoher Score beschreibt vermutete Intensität. Er beweist weder Wahrheit noch Qualität oder tatsächliche Zuschauerbindung.",
    },
    {
        "id": "transkript",
        "label": "Transkript",
        "title": "4. Wortlaut und Rollen prüfen",
        "intro": "Text und Aufnahme bleiben verbunden. Jede interessante Passage lässt sich direkt gegenhören.",
        "image": "06-transkript.png",
        "caption": "Sprecher wurden in Interviewerin und Gast umbenannt; die Suche filtert nach Angst.",
        "steps": [
            (
                "Rollen benennen",
                "S1 und S2 unten im Transkript umbenennen. Die Namen bleiben im jeweiligen Browser gespeichert.",
            ),
            (
                "Gezielt suchen",
                "Suchfeld, Sprecherfilter und Heat-Filter verwenden. Markierte Zitate und Tags helfen beim Sichten.",
            ),
            (
                "Gegenhören",
                "Ein Segment anklicken: Der Player springt an die passende Stelle und startet die Wiedergabe.",
            ),
        ],
        "result": "Du prüfst Formulierung, Sprecherzuordnung und Aussage im tatsächlichen Audio-Kontext.",
        "note": "Schweizerdeutsch wird näherungsweise ins Hochdeutsche übertragen. Ein geprüftes Zitat stimmt mit dem Transkript überein; ASR-Fehler müssen trotzdem am Audio korrigiert werden.",
    },
    {
        "id": "schnitt",
        "label": "Schnitt",
        "title": "5. Vorschläge vorhören",
        "intro": "Schnitt-Ebenen machen verschiedene Verwendungen des gleichen Interviews vergleichbar.",
        "image": "07-clips.png",
        "caption": "Clips-Tab mit Titel, Zeitbereich, Begründung, Originaltext und Vorhören-Button.",
        "steps": [
            (
                "Verwendung wählen",
                "Hook, Clips, 3 / 5 / 10 Min oder Kürzen auswählen. Die Balken auf der Zeitachse wechseln mit.",
            ),
            (
                "Passage anhören",
                "Vorhören startet am vorgeschlagenen Anfang und stoppt am Ende des Clips. Zum Transkript öffnet den Kontext.",
            ),
            (
                "Redaktionell entscheiden",
                "Hook: 5 bis 15 Sekunden. Clips: 15 bis 60 Sekunden, bei geeignetem Material bis zu acht Vorschläge. Pointe, Zusammenhang und Bildausschnitt prüfen.",
            ),
        ],
        "result": "Du wählst geeignete Passagen aus, bevor du sie im Schnittprogramm zusammensetzt.",
        "note": "Kurzfassungen verwenden ein Zielbudget. Eine kurze Aufnahme wird nicht künstlich auf fünf oder zehn Minuten verlängert; die Auswahl kann deutlich kürzer sein.",
    },
    {
        "id": "export",
        "label": "Export",
        "title": "6. Im Schnitt weiterarbeiten",
        "intro": "Die gewählte Schnittversion und das Transkript lassen sich direkt aus dem Report exportieren.",
        "image": "08-kurzfassung.png",
        "image2": "09-export.png",
        "caption": "Eine Kurzfassung als Auswahl von Passagen. Bei der 2:50-Minuten-Demo bleibt auch die 5-Minuten-Version unter dem Zielbudget.",
        "steps": [
            (
                "Version wählen",
                "Zum Beispiel 5 Min auswählen und oben EDL laden. Der EDL-Button folgt der gewählten Hook-, Clip- oder Kurzfassungs-Ebene.",
            ),
            (
                "Daten übernehmen",
                "JSON enthält die Analyse, SRT das vollständige Transkript als Untertitel. Untertitel pro Clip lassen sich an der Clip-Karte laden.",
            ),
            (
                "Medien zuordnen",
                "Bei aktivem Rendern liegen Hook und Social Clips zusätzlich im lokalen output/uploads/<Auftrag>/output/clips-Ordner.",
            ),
        ],
        "result": "Schnittliste, Untertitel und Rohdaten sind für die weitere Bearbeitung verfügbar.",
        "note": "EDL vor dem finalen Schnitt auf Framerate, Source-Timecode und Medienzuordnung prüfen. Der Parser ist geprüft; ein direkter Import in Premiere oder Resolve ist noch nicht bestätigt.",
    },
    {
        "id": "lokal",
        "label": "Im Alltag",
        "title": "Lokal arbeiten. Ergebnisse prüfen.",
        "intro": "Der Standard-Workflow benötigt keine Cloud-API. Audio, Text und Ergebnisse bleiben auf dem Laptop.",
        "image": "02-einstellungen.png",
        "caption": "Ollama als lokale Inhaltsanalyse; Remote-Whisper ist ausdrücklich ausgeschaltet.",
        "steps": [
            (
                "Erststart",
                "Python 3.11+, ffmpeg und Ollama mit lokalem Chat-Modell bereitstellen. Whisper- und Sprechergewichte werden einmal geladen.",
            ),
            (
                "Ohne Cloud arbeiten",
                "Whisper und die noScribe-Sprechergewichte verarbeiten Audio lokal. Ollama erstellt die Inhaltsanalyse über die lokale Loopback-Verbindung.",
            ),
            (
                "Erneut öffnen",
                "In Deine Interviews den Report öffnen. Neues Interview startet einen neuen Auftrag; Medium wählen im Report setzt die Wiedergabedatei.",
            ),
        ],
        "result": "Ein lokaler Arbeitsablauf mit überprüfbaren Ergebnissen und eigenständigem HTML-Report.",
        "note": "Laufzeit und Qualität hängen von Aufnahme, Modell und Hardware ab. Emotionen und Retention-Risiken sind redaktionelle Hinweise. Für neue API-Modi gelten deren ausdrückliche Freigaben.",
    },
]


def image_uri(name):
    return "data:image/png;base64," + base64.b64encode((SHOTS / name).read_bytes()).decode()


def build_html():
    esc = html.escape
    navigation = "".join(
        f'<a href="#{p["id"]}">{i + 1:02} {esc(p["label"])}</a>' for i, p in enumerate(PAGES)
    )
    sections = []
    for i, p in enumerate(PAGES):
        extra = (
            f'<button class="zoom export-shot" aria-label="Export-Buttons vergrössern"><img src="{image_uri(p["image2"])}" alt="JSON-, EDL- und SRT-Export-Buttons im Report"></button>'
            if p.get("image2")
            else ""
        )
        steps = "".join(
            f'<li><span class="number">{j + 1}</span><div><h3>{esc(title)}</h3><p>{esc(text)}</p></div></li>'
            for j, (title, text) in enumerate(p["steps"])
        )
        sections.append(f'''<section id="{p["id"]}" class="chapter">
<div class="chapter-head"><span class="eyebrow">{i + 1:02} / 08 · {esc(p["label"])}</span><h2>{esc(p["title"])}</h2><p class="intro">{esc(p["intro"])}</p></div>
<div class="chapter-grid"><figure>{extra}<button class="zoom" aria-label="Screenshot vergrössern: {esc(p["label"])}"><img src="{image_uri(p["image"])}" alt="{esc(p["caption"])}" loading="lazy"></button><figcaption>{esc(p["caption"])}</figcaption></figure>
<div class="instructions"><ol>{steps}</ol><div class="result"><span class="eyebrow">Ergebnis</span><p>{esc(p["result"])}</p></div><p class="note">{esc(p["note"])}</p></div></div></section>''')
    overview = "".join(
        f'<a href="#{p["id"]}"><b>{i + 1:02}</b><span>{esc(p["label"])}</span></a>'
        for i, p in enumerate(PAGES[1:7], 1)
    )
    document = f"""<!doctype html><html lang="de-CH"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Schnittplatz · Bebilderte Vorstellung</title>
<style>
:root{{--bg:#f4f3ef;--panel:#fff;--ink:#202c2b;--muted:#6e7976;--line:#dfe4dd;--green:#355b50;--soft:#eaf0e8;--orange:#db6a43}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:100px}}body{{margin:0;font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--ink)}}a{{color:var(--green)}}.topbar{{position:sticky;top:0;z-index:10;background:#f4f3eff5;backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}}.top-inner{{max-width:1400px;margin:auto;padding:16px 32px;display:flex;align-items:center;justify-content:space-between;gap:20px}}.brand{{font-weight:750;letter-spacing:-.4px;display:flex;gap:10px;align-items:center}}.logo{{background:var(--green);color:white;padding:0 7px;border-radius:6px;font-size:22px}}.brand small{{color:var(--muted);font-weight:400;margin-left:12px}}.actions{{display:flex;gap:8px}}.button{{display:inline-block;padding:7px 13px;border:1px solid var(--line);border-radius:6px;text-decoration:none;font-size:12px;background:white}}.primary{{background:var(--green);color:white;border-color:var(--green)}}main{{max-width:1400px;margin:auto;padding:0 32px}}.hero{{padding:55px 0 32px;display:grid;grid-template-columns:1.3fr 1fr;gap:60px;align-items:end}}.eyebrow{{font-size:10px;letter-spacing:1.7px;text-transform:uppercase;font-weight:700;color:var(--muted)}}h1{{font-size:clamp(34px,4.2vw,58px);line-height:1.08;letter-spacing:-2px;margin:15px 0 22px}}h1 span{{color:var(--muted)}}.hero p{{color:var(--muted);max-width:640px;margin:0}}.demo-note{{padding:18px 22px;background:var(--soft);border-radius:10px;font-size:13px;color:var(--green)}}.demo-note strong{{display:block;margin-bottom:7px}}.flow{{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid var(--line);border-radius:12px;overflow:hidden;background:white;margin:20px 0 18px}}.flow a{{display:flex;gap:11px;align-items:center;text-decoration:none;padding:20px;border-right:1px solid var(--line);font-size:13px}}.flow a:last-child{{border:0}}.flow b{{color:var(--orange);font-size:11px}}.toc{{display:flex;gap:17px;flex-wrap:wrap;padding:10px 0 20px;font-size:11px}}.toc a{{text-decoration:none;color:var(--muted)}}.toc a[aria-current=true]{{color:var(--green);font-weight:750}}.chapter{{padding:42px 0 48px;border-top:1px solid var(--line);scroll-margin-top:80px}}.chapter-head{{margin-bottom:26px}}h2{{font-size:32px;letter-spacing:-1px;line-height:1.2;margin:10px 0 12px}}.intro{{color:var(--muted);max-width:880px;margin:0}}.chapter-grid{{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(290px,1fr);gap:35px;align-items:start}}figure{{margin:0;min-width:0}}.zoom{{display:block;width:100%;background:white;border:1px solid var(--line);border-radius:10px;padding:0;overflow:hidden;cursor:zoom-in;box-shadow:0 6px 22px #2441360b}}figure img{{display:block;width:100%;height:auto;max-height:650px;object-fit:contain;object-position:top}}figcaption{{color:var(--muted);font-size:11px;margin-top:11px;line-height:1.6}}.instructions ol{{list-style:none;padding:0;margin:0}}.instructions li{{display:flex;gap:13px;padding:15px 0;border-bottom:1px solid var(--line)}}.instructions li:first-child{{padding-top:0}}.number{{display:grid;place-items:center;flex:0 0 25px;height:25px;border-radius:50%;background:var(--soft);color:var(--green);font-size:11px;font-weight:700}}h3{{font-size:14px;margin:0 0 4px}}.instructions p{{font-size:13px;color:var(--muted);margin:0}}.result{{margin-top:20px;background:var(--soft);padding:16px 18px;border-radius:8px}}.result p{{color:var(--green);margin-top:5px}}.instructions .note{{margin-top:16px;font-size:11px;line-height:1.7}}.footer{{padding:26px 0 35px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:25px;font-size:11px;color:var(--muted)}}dialog{{width:min(1400px,96vw);height:94vh;border:0;padding:20px;background:var(--bg);border-radius:12px}}dialog::backdrop{{background:#12231fd9}}dialog img{{width:100%;height:calc(100% - 45px);object-fit:contain}}dialog button{{float:right;border:1px solid var(--line);border-radius:6px;padding:7px 12px;background:white;cursor:pointer}}button:focus-visible,a:focus-visible{{outline:2px solid var(--orange);outline-offset:4px}}.tip{{font-size:11px;color:var(--muted)}}.export-shot{{margin-bottom:16px}}
@media(max-width:900px){{main{{padding:0 18px}}.top-inner{{padding:13px 18px}}.brand small{{display:none}}.hero,.chapter-grid{{grid-template-columns:1fr;gap:24px}}.hero{{padding-top:35px}}.flow{{grid-template-columns:repeat(3,1fr)}}.flow a{{padding:14px}}.flow a:nth-child(3){{border:0}}.flow a:nth-child(-n+3){{border-bottom:1px solid var(--line)}}h2{{font-size:27px}}.footer{{flex-direction:column;gap:8px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}@media print{{.topbar,.toc,.flow,dialog{{display:none}}.hero{{padding-top:0}}.chapter{{break-before:page}}.chapter-grid{{grid-template-columns:1.45fr 1fr}}figure img{{max-height:480px}}.chapter{{padding-top:20px}}}}
</style></head><body><header class="topbar"><div class="top-inner"><div class="brand"><span class="logo">≋</span>Schnittplatz<small>Produkttour mit echten Screenshots</small></div><div class="actions"><a class="button" href="vorstellung.pdf" download="Schnittplatz-Vorstellung.pdf">PDF herunterladen</a><a class="button primary" href="http://localhost:8767/">Tool öffnen</a></div></div></header>
<main><div class="hero"><div><span class="eyebrow">Interview Heatmap & Schnitt-Advisor</span><h1>Vom Interview<br><span>zum Schnittplan.</span></h1><p>Eine bebilderte Vorstellung des lokalen Tools. Acht Stationen zeigen, wie aus einer Aufnahme ein prüfbarer Report mit Schnittvorschlägen entsteht.</p></div><aside class="demo-note"><strong>Durchgehendes Demo-Beispiel</strong>Fiktives Interview über ein Quartiercafé, rund 2:50 Minuten, zwei synthetische Stimmen. Alle Screenshots stammen aus einem echten lokalen Durchlauf mit Whisper, Sprechererkennung und Ollama.</aside></div>
<div class="flow" aria-label="Arbeitsablauf">{overview}</div><nav class="toc" aria-label="Kapitel">{navigation}</nav><p class="tip">Screenshots anklicken, um sie in voller Grösse zu lesen. Die PDF-Fassung enthält denselben Ablauf auf acht Seiten.</p>
{"".join(sections)}<footer class="footer"><span>Stand: 24. Oktober 2026 · Schweizer Orthografie · Synthetische Demo</span><span>Projektcode: MIT · Modellgewichte: eigene Bedingungen · <a href="https://github.com/Witzelfitz/interview-heatmap">GitHub</a></span></footer></main>
<dialog id="lightbox"><button id="close">Schliessen</button><img alt="Vergrösserter Screenshot" id="large"></dialog>
<script>const box=document.getElementById('lightbox');for(const button of document.querySelectorAll('.zoom'))button.onclick=()=>{{const source=button.querySelector('img');document.getElementById('large').src=source.src;document.getElementById('large').alt=source.alt;box.showModal()}};document.getElementById('close').onclick=()=>box.close();box.addEventListener('click',event=>{{if(event.target===box)box.close()}});const observer=new IntersectionObserver(entries=>{{for(const entry of entries)if(entry.isIntersecting)for(const a of document.querySelectorAll('.toc a'))a.setAttribute('aria-current',String(a.hash==='#'+entry.target.id))}},{{rootMargin:'-15% 0px -60% 0px'}});for(const section of document.querySelectorAll('.chapter'))observer.observe(section);</script></body></html>"""
    (DOCS / "vorstellung.html").write_text(document, encoding="utf-8")


BG, PANEL, INK, MUTED, LINE, GREEN, SOFT, ORANGE = [
    HexColor(c)
    for c in ("#f4f3ef", "#ffffff", "#202c2b", "#6e7976", "#dfe4dd", "#355b50", "#eaf0e8", "#db6a43")
]
W, H = 1280, 800


def paragraph(c, text, x, top, width, size=16, leading=None, color=INK, bold=False):
    style = ParagraphStyle(
        "body",
        fontName="GuideBold" if bold else "Guide",
        fontSize=size,
        leading=leading or size * 1.5,
        textColor=color,
        spaceAfter=0,
    )
    p = Paragraph(html.escape(text), style)
    _, height = p.wrap(width, H)
    p.drawOn(c, x, top - height)
    return top - height


def screenshot(c, name, x, y, width, height):
    path = SHOTS / name
    with Image.open(path) as source:
        iw, ih = source.size
    scale = min(width / iw, height / ih)
    dw, dh = iw * scale, ih * scale
    px, py = x + (width - dw) / 2, y + height - dh
    c.setFillColor(PANEL)
    c.setStrokeColor(LINE)
    c.roundRect(px - 2, py - 2, dw + 4, dh + 4, 7, fill=1, stroke=1)
    c.drawImage(str(path), px, py, dw, dh, mask="auto")
    return py


def build_pdf():
    fonts = Path("/System/Library/Fonts/Supplemental")
    regular, bold = fonts / "Arial.ttf", fonts / "Arial Bold.ttf"
    if not regular.exists():
        import reportlab

        fonts = Path(reportlab.__file__).parent / "fonts"
        regular, bold = fonts / "Vera.ttf", fonts / "VeraBd.ttf"
    pdfmetrics.registerFont(TTFont("Guide", str(regular)))
    pdfmetrics.registerFont(TTFont("GuideBold", str(bold)))
    output = ROOT / "output/pdf"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "schnittplatz-vorstellung.pdf"
    c = canvas.Canvas(str(target), pagesize=(W, H), pageCompression=1)
    c.setTitle("Schnittplatz - Bebilderte Produktvorstellung")
    c.setAuthor("Interview Heatmap contributors")
    c.setSubject("Lokaler Interview-Workflow mit echten Screenshots einer synthetischen Demo")
    for i, page in enumerate(PAGES):
        c.setFillColor(BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        c.bookmarkPage(page["id"])
        c.addOutlineEntry(page["label"], page["id"], 0)
        c.setFillColor(GREEN)
        c.roundRect(46, 737, 27, 27, 6, fill=1, stroke=0)
        c.setFillColor(PANEL)
        c.setFont("GuideBold", 19)
        c.drawString(51, 743, "S")
        c.setFillColor(INK)
        c.setFont("GuideBold", 14)
        c.drawString(83, 746, "Schnittplatz")
        c.setFillColor(MUTED)
        c.setFont("Guide", 10)
        c.drawRightString(W - 46, 747, "PRODUKTVORSTELLUNG  /  SYNTHETISCHE DEMO")
        c.setStrokeColor(LINE)
        c.line(46, 724, W - 46, 724)
        paragraph(c, f"{i + 1:02} / 08    {page['label'].upper()}", 48, 703, 600, 10, color=MUTED, bold=True)
        paragraph(c, page["title"], 46, 677, W - 92, 34, leading=39, bold=True)
        paragraph(c, page["intro"], 48, 625, W - 96, 15, color=MUTED)
        if i in (0, 3, 5):
            # Breite UI-Ausschnitte bleiben gross, Anleitung als kompakte Spalte.
            image_x, image_w, text_x, text_w = 46, 807, 887, 347
        else:
            image_x, image_w, text_x, text_w = 46, 656, 744, 490
        if page.get("image2"):
            screenshot(c, page["image2"], image_x, 519, image_w, 65)
            bottom = screenshot(c, page["image"], image_x, 153, image_w, 345)
        else:
            bottom = screenshot(c, page["image"], image_x, 153, image_w, 431)
        paragraph(c, page["caption"], image_x, bottom - 13, image_w, 10, leading=14, color=MUTED)
        top = 583
        for j, (title, body) in enumerate(page["steps"]):
            c.setFillColor(SOFT)
            c.circle(text_x + 12, top - 12, 12, fill=1, stroke=0)
            c.setFillColor(GREEN)
            c.setFont("GuideBold", 10)
            c.drawCentredString(text_x + 12, top - 15, str(j + 1))
            y = paragraph(c, title, text_x + 36, top, text_w - 36, 14, bold=True)
            top = paragraph(c, body, text_x + 36, y - 6, text_w - 36, 13, leading=19, color=MUTED) - 23
        result_height = 76
        if top - result_height < 145:
            result_height = 62
        c.setFillColor(SOFT)
        c.roundRect(text_x, top - result_height, text_w, result_height, 8, fill=1, stroke=0)
        paragraph(c, "ERGEBNIS", text_x + 14, top - 12, text_w - 28, 9, color=GREEN, bold=True)
        paragraph(c, page["result"], text_x + 14, top - 29, text_w - 28, 12, leading=17, color=GREEN)
        c.setStrokeColor(LINE)
        c.line(46, 104, W - 46, 104)
        c.setFillColor(ORANGE)
        c.rect(47, 61, 3, 26, fill=1, stroke=0)
        paragraph(c, page["note"], 60, 89, W - 120, 11, leading=16, color=MUTED)
        c.setFillColor(MUTED)
        c.setFont("Guide", 9)
        c.drawString(
            47, 25, "24. Oktober 2026  |  Demo: Quartiercafe, 2:50 Minuten, zwei synthetische Stimmen"
        )
        c.drawRightString(W - 47, 25, f"{i + 1:02} / 08")
        c.linkURL("http://localhost:8767/", (46, 736, 180, 767), relative=0)
        c.showPage()
    c.save()
    shutil.copy2(target, DOCS / "vorstellung.pdf")
    print(f"PDF erstellt: {target}")


if __name__ == "__main__":
    capture = json.loads((SHOTS / "capture.json").read_text())
    if not capture.get("synthetic"):
        raise ValueError("Nur ausdrücklich synthetische Demo-Screenshots verwenden")
    build_html()
    build_pdf()
