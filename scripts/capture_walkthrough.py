"""Authentische Screenshots einer isolierten Demo; keine privaten Interviewdaten."""

import argparse
import json
import re
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from heatmap import ROOT
from server import Jobs, LocalServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path, help="Ausschliesslich eine synthetische Demo-Aufnahme verwenden")
    parser.add_argument("--data", type=Path, default=Path("test-output/walkthrough"))
    parser.add_argument("--screenshots", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    jobs = Jobs(args.data, ROOT / "config.yaml")
    server = LocalServer(("127.0.0.1", 0), jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base)
            page.wait_for_function("capabilities !== null")
            page.locator("#file").set_input_files(str(args.media.resolve()))
            page.screenshot(path=str(args.screenshots / "01-upload.png"), full_page=True)
            page.locator(".grid > section").first.screenshot(
                path=str(args.screenshots / "01-upload-panel.png")
            )
            print("Screenshot 01: Upload", flush=True)
            page.locator("#settings > summary").click()
            page.locator("#settings").screenshot(path=str(args.screenshots / "02-einstellungen.png"))
            page.locator("#settings > summary").click()
            page.get_by_role("button", name="Interview hochladen & analysieren").click()
            page.wait_for_function(
                "document.getElementById('job-state').textContent === 'Analysiert'", timeout=30000
            )
            page.locator(".grid > section").nth(1).screenshot(
                path=str(args.screenshots / "03-verarbeitung.png")
            )
            # Noch ein echter Zwischenstand, sobald der Prozess in die Inhaltsanalyse wechselt.
            deadline = time.monotonic() + 900
            job_id = None
            while time.monotonic() < deadline:
                records = list(jobs.records.values())
                if records:
                    job = jobs.get(records[-1]["id"])
                    job_id = job["id"]
                    if job["state"] == "failed":
                        raise RuntimeError(job["error"])
                    if job["stage"] >= 4 or job["state"] == "done":
                        break
                page.wait_for_timeout(1000)
            if not job_id:
                raise RuntimeError("Kein Demo-Auftrag angelegt")
            page.wait_for_url(re.compile(r"/jobs/[0-9a-f]{32}/report.html$"), timeout=900000)
            page.wait_for_selector(".segment")
            page.wait_for_function("document.querySelector('audio,video').readyState >= 1")
            data = json.loads((jobs.directory / job_id / "output/report.json").read_text())
            assert data["metadata"]["filename"] == args.media.name
            assert data["metadata"]["diarization"] == "noscribe_local"
            assert data["analysis"]["mode"] == "ollama"
            page.screenshot(path=str(args.screenshots / "04-report.png"), full_page=True)
            page.locator("main > section.panel").first.screenshot(
                path=str(args.screenshots / "05-heatmap.png")
            )
            page.get_by_label("Name für S1").fill("Interviewerin")
            page.get_by_label("Name für S1").press("Tab")
            page.get_by_label("Name für S2").fill("Gast")
            page.get_by_label("Name für S2").press("Tab")
            page.get_by_placeholder("Im Gespräch suchen …").fill("Angst")
            page.locator(".workspace > section").first.screenshot(
                path=str(args.screenshots / "06-transkript.png")
            )
            page.get_by_placeholder("Im Gespräch suchen …").fill("")
            page.get_by_role("tab", name="Clips", exact=True).click()
            page.locator(".clip-card button").filter(has_text="Vorhören").first.click()
            page.wait_for_function("!document.querySelector('audio,video').paused")
            page.wait_for_function(
                "document.querySelector('audio,video').currentTime > "
                + str(data["cuts"]["clips"][0]["start"] + 0.25)
            )
            page.locator(".workspace").screenshot(path=str(args.screenshots / "07-clips.png"))
            page.locator("audio,video").evaluate("p=>p.pause()")
            page.get_by_role("tab", name="5 Min", exact=True).click()
            page.locator(".workspace > section").nth(1).screenshot(
                path=str(args.screenshots / "08-kurzfassung.png")
            )
            page.locator(".topbar").scroll_into_view_if_needed()
            page.locator(".actions").screenshot(path=str(args.screenshots / "09-export.png"))
            with page.expect_download() as download:
                page.locator("#export-edl").click()
            assert "FCM: NON-DROP FRAME" in Path(download.value.path()).read_text()
            page.get_by_label("Farbschema wechseln").click()
            page.locator(".workspace").scroll_into_view_if_needed()
            page.screenshot(path=str(args.screenshots / "10-darkmode.png"), full_page=True)
            assert not errors, errors
            manifest = {
                "filename": args.media.name,
                "synthetic": True,
                "duration": data["metadata"]["duration"],
                "speakers": sorted({s["speaker"] for s in data["scored"]["segments"]}),
                "model": data["analysis"]["model"],
                "asr": data["transcript"]["provenance"],
                "screenshots": sorted(path.name for path in args.screenshots.glob("*.png")),
            }
            (args.screenshots / "capture.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            print("Screenshots vollständig; echte lokale Pipeline und Export geprüft.", flush=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        jobs.pool.shutdown(wait=True)
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
