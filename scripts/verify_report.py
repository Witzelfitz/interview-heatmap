"""Echter file://-Browsertest für einen generierten Report, inkl. Playback und Downloads."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    path = Path(sys.argv[1]).resolve()
    data = json.loads(path.with_name("report.json").read_text())
    screenshots = path.parent / "screenshots"
    screenshots.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
        errors, network = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda req: network.append(req.url) if req.url.startswith(("https:", "http:")) else None,
        )
        page.goto(path.as_uri())
        page.wait_for_selector(".segment")
        page.wait_for_function('document.querySelector("audio,video").readyState >= 1')
        assert page.locator(".segment").count() == len(data["scored"]["segments"])
        page.screenshot(path=str(screenshots / "report-light.png"), full_page=True)
        page.get_by_role("tab", name="Clips", exact=True).click()
        first = data["cuts"]["clips"][0]
        page.locator(".clip-card button").filter(has_text="Vorhören").first.click()
        page.wait_for_function(
            '(expected) => Math.abs(document.querySelector("audio,video").currentTime - expected) < 1',
            arg=first["start"],
        )
        # Clip-Ende wirklich testen, ohne die ganze Passage abwarten zu müssen.
        page.evaluate(
            '(end)=>{const p=document.querySelector("audio,video");p.currentTime=end-.15;p.play()}',
            first["end"],
        )
        page.wait_for_function('document.querySelector("audio,video").paused', timeout=5000)
        assert abs(page.locator("audio,video").evaluate("(p)=>p.currentTime") - first["end"]) < 0.15
        # Gegenseitige Verknüpfung und Filter.
        page.get_by_placeholder("Im Gespräch suchen …").fill("definitely-no-match-48291")
        assert page.locator(".segment").count() == 0
        page.get_by_placeholder("Im Gespräch suchen …").fill("")
        name = page.get_by_label("Name für S1")
        name.fill("Interviewerin")
        name.press("Tab")
        assert page.locator(".speaker").first.inner_text().startswith("Interviewerin")
        page.reload()
        page.wait_for_selector(".segment")
        assert page.get_by_label("Name für S1").input_value() == "Interviewerin"
        # Namen für den ausgelieferten Demo-Zustand wieder zurücksetzen.
        page.get_by_label("Name für S1").fill("S1")
        page.get_by_label("Name für S1").press("Tab")
        with page.expect_download() as pending:
            page.locator("#export-json").click()
        result = json.loads(Path(pending.value.path()).read_text())
        assert result["metadata"]["sha256"] == data["metadata"]["sha256"]
        for selector, expected in [("#export-edl", "FCM: NON-DROP FRAME"), ("#export-srt", "-->")]:
            with page.expect_download() as pending:
                page.locator(selector).click()
            assert expected in Path(pending.value.path()).read_text()
        page.get_by_label("Farbschema wechseln").click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.screenshot(path=str(screenshots / "report-dark.png"), full_page=True)
        page.set_viewport_size({"width": 768, "height": 1024})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "report-tablet.png"), full_page=True)
        assert not errors, errors
        assert not network, network
        browser.close()
        print(
            "Browser OK: file://, seek, Clip-Stopp, Suche, Namen, Downloads, Dark Mode, 768px, 0 Netzwerkaufrufe."
        )


if __name__ == "__main__":
    main()
