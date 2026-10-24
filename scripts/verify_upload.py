"""Browser → Upload → echter lokaler CLI-Prozess → Report und Exporte."""

import argparse
import json
import re
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from heatmap import ROOT
from server import Jobs, LocalServer


def main():
    parser = argparse.ArgumentParser(
        description="Echter Browser-Uploadtest mit einer Ein-Stimmen-Testaufnahme"
    )
    parser.add_argument(
        "media", type=Path, help="Tatsächliche Ein-Stimmen-Aufnahme, keine Mehrsprecher-Datei"
    )
    parser.add_argument("--out", type=Path, default=Path("test-output/upload-browser"))
    parser.add_argument("--llm", choices=["local", "ollama"], default="ollama")
    args = parser.parse_args()
    jobs = Jobs(args.out, ROOT / "config.yaml")
    server = LocalServer(("127.0.0.1", 0), jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    errors, external = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    external.append(request.url)
                    if request.url.startswith("http") and not request.url.startswith(base + "/")
                    else None
                ),
            )
            page.goto(base)
            page.wait_for_function("capabilities !== null")
            page.locator("#llm").select_option(args.llm)
            page.locator("#file").set_input_files(str(args.media.resolve()))
            if not jobs.capabilities()["hf_token"]:
                page.get_by_role("button", name="Interview hochladen & analysieren").click()
                assert "Hugging-Face" in page.locator("#form-error").inner_text()
                assert not jobs.records
            page.locator("#speaker-mode").select_option("single")
            page.locator("#model").select_option("tiny")
            page.screenshot(path=str(args.out / "upload-light.png"), full_page=True)
            page.get_by_role("button", name="Farbschema wechseln").click()
            page.set_viewport_size({"width": 768, "height": 1024})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.out / "upload-dark-tablet.png"), full_page=True)
            page.get_by_role("button", name="Farbschema wechseln").click()
            page.set_viewport_size({"width": 1440, "height": 1050})
            page.get_by_role("button", name="Interview hochladen & analysieren").click()
            page.wait_for_url(re.compile(r"/jobs/[0-9a-f]{32}/report.html$"), timeout=600000)
            job_id = page.url.split("/jobs/")[1].split("/")[0]
            page.wait_for_selector(".segment")
            page.wait_for_function('document.querySelector("audio,video").readyState >= 1')
            result = jobs.get(job_id)
            assert result["state"] == "done" and result["stage"] == 7
            folder = jobs.directory / job_id
            output = folder / "output"
            data = json.loads((output / "report.json").read_text())
            assert data["metadata"]["diarization"] == "single_speaker_explicit"
            assert not data["metadata"]["audio_remote"] and not data["metadata"]["text_remote"]
            assert data["analysis"]["mode"] == ("ollama" if args.llm == "ollama" else "local_heuristic")
            for step in range(1, 8):
                assert f"{step}/7" in (folder / "pipeline.log").read_text()
            for name in (
                "report.html",
                "report.json",
                "transcript.json",
                "transcript.srt",
                "transcript.txt",
                "audio_features.json",
                "analysis.json",
                "heatmap.json",
                "cuts.json",
                "cuts.edl",
            ):
                assert (output / name).is_file(), name
            assert list((output / "clips").glob("*.m4a"))
            page.locator(".segment").first.click()
            page.wait_for_function('!document.querySelector("audio,video").paused')
            page.screenshot(path=str(args.out / "uploaded-report.png"), full_page=True)
            page.get_by_role("link", name="+ Neues Interview").click()
            page.wait_for_function("capabilities !== null")
            assert page.get_by_role("link", name="Report öffnen →", exact=True).count() >= 1
            # Ungültige Aufnahme muss als Fehler erscheinen, nie als fertiger Report.
            page.locator("#speaker-mode").select_option("single")
            page.locator("#model").select_option("tiny")
            page.locator("#file").set_input_files(
                {"name": "kaputt.wav", "mimeType": "audio/wav", "buffer": b"not an audio file"}
            )
            page.get_by_role("button", name="Interview hochladen & analysieren").click()
            page.wait_for_function(
                'document.getElementById("job-state").textContent === "Fehler"', timeout=30000
            )
            assert "Medienverarbeitung" in page.locator("#job-error").inner_text()
            assert page.locator("#retry").is_visible()
            assert not errors, errors
            assert not external, external
            browser.close()
            print(
                f"Upload E2E OK: {job_id}, {len(data['scored']['segments'])} Segmente, 7 echte Pipeline-Schritte, Rendering, Playback, Exporte, Fehleranzeige, 0 externe Browser-Anfragen."
            )
    finally:
        server.shutdown()
        server.server_close()
        jobs.pool.shutdown(wait=True)
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
